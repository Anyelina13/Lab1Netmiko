"""
ITIEL-13 Redes Programables - Laboratorio 1
Inventario, estado y configuración segura con Python + SSH (Netmiko).

Uso:
    export LAB_PASS_MT_LAB='la-clave'     # opcional, si no existe se pide
    python lab1_inventario.py             # estado + asegurar mi loopback
    python lab1_inventario.py --limpiar   # estado + borrar solo mis objetos
"""

import argparse
import os
import re
import sys
import getpass
import json
from datetime import datetime

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)

ARCHIVO_INVENTARIO = "inventario.yaml"
CARPETA_LOGS = "logs"
ARCHIVO_REPORTE = "reporte_estado.json"

# Campos que debe traer cada equipo del inventario
CAMPOS_OBLIGATORIOS = ["nombre", "host", "device_type", "usuario", "rol"]
ROLES_VALIDOS = ["lectura", "escritura"]


def cargar_inventario(ruta):
    """Lee el YAML y devuelve la lista de equipos ya revisada."""
    with open(ruta, encoding="utf-8") as archivo:
        datos = yaml.safe_load(archivo)

    equipos = (datos or {}).get("equipos", [])
    if not equipos:
        raise ValueError(f"El inventario {ruta} no tiene equipos")

    for equipo in equipos:
        # Si falta un campo es mejor avisar aquí que fallar a media conexión
        faltantes = [campo for campo in CAMPOS_OBLIGATORIOS if campo not in equipo]
        if faltantes:
            nombre = equipo.get("nombre", "(sin nombre)")
            raise ValueError(f"Al equipo {nombre} le faltan los campos: {faltantes}")
        if equipo["rol"] not in ROLES_VALIDOS:
            raise ValueError(
                f"Rol '{equipo['rol']}' no válido en {equipo['nombre']} "
                f"(debe ser lectura o escritura)"
            )
    return equipos


def cargar_estudiante(ruta):
    """Lee el número de lista N y el nombre del bloque 'estudiante' del YAML.

    Devuelve None si no están, y en ese caso no se cambia nada en los equipos.
    """
    with open(ruta, encoding="utf-8") as archivo:
        datos = yaml.safe_load(archivo) or {}

    estudiante = datos.get("estudiante") or {}
    numero = estudiante.get("numero_lista")
    nombre = estudiante.get("nombre")
    if numero is None or not nombre:
        return None
    # N se usa en la IP 10.253.0.N, entonces tiene que ser un host válido
    if not isinstance(numero, int) or not 1 <= numero <= 254:
        raise ValueError(f"numero_lista debe ser un entero entre 1 y 254, no {numero!r}")
    return {"numero_lista": numero, "nombre": nombre}


def nombre_variable(nombre_equipo):
    """mt-lab -> LAB_PASS_MT_LAB (mayúsculas y guiones como guion bajo)."""
    return "LAB_PASS_" + nombre_equipo.upper().replace("-", "_")


def obtener_clave(equipo):
    """Busca la clave en la variable de entorno; si no existe, la pide."""
    variable = nombre_variable(equipo["nombre"])
    clave = os.getenv(variable)
    if clave:
        return clave
    # getpass no muestra lo que se escribe en la terminal
    return getpass.getpass(
        f"Contraseña de '{equipo['usuario']}' en {equipo['nombre']} ({variable} no definida): "
    )


# ---------------------------------------------------------------------------
# Lectura de la salida de los equipos
# ---------------------------------------------------------------------------

def texto_a_dict(texto):
    """Convierte líneas 'clave: valor' (ej. /system resource print) en dict."""
    datos = {}
    for linea in texto.splitlines():
        if ":" not in linea:
            continue
        clave, valor = linea.split(":", 1)
        datos[clave.strip()] = valor.strip()
    return datos


# clave=valor, donde el valor puede tener espacios (ej. comment=Mi equipo)
PATRON_TERSE = re.compile(r"([\w.-]+)=(.*?)(?=\s+[\w.-]+=|$)")


def terse_a_lista(texto):
    """Convierte la salida de 'print terse' de RouterOS en una lista de dicts.

    Cada línea es un registro, por ejemplo:
        0   address=10.60.30.202/24 network=10.60.30.0 interface=ether1
    Lo que va antes del primer 'clave=' es el número y las banderas (X, D, A...).
    """
    registros = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if "=" not in linea:
            continue
        registro = dict(PATRON_TERSE.findall(linea))
        inicio = linea[: linea.index("=")].rsplit(" ", 1)[0]
        partes = inicio.split()
        if partes and partes[0].isdigit():
            registro["flags"] = "".join(partes[1:])
        registros.append(registro)
    return registros


def mikrotik_identidad(texto):
    return texto_a_dict(texto).get("name", "")


def mikrotik_recursos(texto):
    recursos = texto_a_dict(texto)
    return {
        "uptime": recursos.get("uptime", ""),
        "version": recursos.get("version", ""),
    }


def mikrotik_interfaces(texto):
    interfaces = []
    for registro in terse_a_lista(texto):
        interfaces.append({
            "interfaz": registro.get("interface", ""),
            "ip": registro.get("address", ""),
            "deshabilitada": "X" in registro.get("flags", ""),
        })
    return interfaces


def mikrotik_ruta_defecto(texto):
    rutas = terse_a_lista(texto)
    # Si hay varias, prefiero la activa (bandera A)
    activas = [r for r in rutas if "A" in r.get("flags", "")]
    ruta = (activas or rutas or [{}])[0]
    return ruta.get("gateway", "")


def cisco_identidad(texto):
    # "hostname R-Cisco" -> "R-Cisco"
    coincidencia = re.search(r"^hostname\s+(\S+)", texto, re.MULTILINE)
    return coincidencia.group(1) if coincidencia else ""


def cisco_recursos(texto):
    # "R-Cisco uptime is 2 hours, 5 minutes" -> "2 hours, 5 minutes"
    coincidencia = re.search(r"uptime is (.+)", texto)
    return {"uptime": coincidencia.group(1).strip() if coincidencia else ""}


def cisco_interfaces(texto):
    """show ip interface brief -> solo las interfaces que tienen IP.

    Columnas: Interface  IP-Address  OK?  Method  Status  Protocol
    El Status puede ser "administratively down" (dos palabras), por eso el
    protocolo se toma de la última columna y el status de lo que queda.
    """
    interfaces = []
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) < 6 or partes[0] == "Interface" or partes[1] == "unassigned":
            continue
        interfaces.append({
            "interfaz": partes[0],
            "ip": partes[1],
            "deshabilitada": "administratively" in partes[4:-1],
        })
    return interfaces


def cisco_ruta_defecto(texto):
    # En "Routing Descriptor Blocks" la ruta en uso va marcada con "* <ip>"
    if "not in table" in texto:
        return ""
    coincidencia = re.search(r"\*\s+(\d+\.\d+\.\d+\.\d+)", texto)
    return coincidencia.group(1) if coincidencia else ""


# Comandos de lectura por device_type: dato -> (comando, función que lo procesa).
# Para otro fabricante basta con agregar su entrada aquí.
COMANDOS_ESTADO = {
    "mikrotik_routeros": {
        "identidad": ("/system identity print", mikrotik_identidad),
        "recursos": ("/system resource print", mikrotik_recursos),
        "interfaces": ("/ip address print terse", mikrotik_interfaces),
        "gateway": (
            "/ip route print terse where dst-address=0.0.0.0/0",
            mikrotik_ruta_defecto,
        ),
    },
    "cisco_ios": {
        "identidad": ("show running-config | include hostname", cisco_identidad),
        "recursos": ("show version | include uptime", cisco_recursos),
        "interfaces": ("show ip interface brief", cisco_interfaces),
        "gateway": ("show ip route 0.0.0.0", cisco_ruta_defecto),
    },
}


# ---------------------------------------------------------------------------
# Cambio de configuración en el MikroTik (solo rol: escritura)
# ---------------------------------------------------------------------------

def objetos_propios(estudiante):
    """Nombre del bridge, IP y comentario que me tocan según mi número N."""
    n = estudiante["numero_lista"]
    return {
        "bridge": f"lo-ssh-{n}",
        "ip": f"10.253.0.{n}/32",
        "comentario": f"Lab1 {estudiante['nombre']}",
    }


def consultar_loopback(conexion, objetos):
    """Revisa qué existe ya en el router. Solo lectura, no cambia nada.

    Los print llevan 'where' con mi nombre exacto para no traer (ni tocar)
    los objetos de los demás.
    """
    bridge = objetos["bridge"]
    bridges = terse_a_lista(conexion.send_command(
        f'/interface bridge print terse where name="{bridge}"'))
    direcciones = terse_a_lista(conexion.send_command(
        f'/ip address print terse where interface="{bridge}"'))
    return {
        "bridge": len(bridges) > 0,
        "ip": any(d.get("address") == objetos["ip"] for d in direcciones),
    }


def asegurar_loopback(conexion, estudiante):
    """Deja creada mi loopback lo-ssh-<N> con su IP, sin duplicar nada.

    1. Consulta qué existe.
    2. Manda solo los comandos de lo que falta (si no falta nada, no manda nada).
    3. Vuelve a consultar para verificar que el cambio quedó.
    """
    objetos = objetos_propios(estudiante)
    antes = consultar_loopback(conexion, objetos)

    comandos = []
    if not antes["bridge"]:
        comandos.append(
            f'/interface bridge add name="{objetos["bridge"]}" '
            f'comment="{objetos["comentario"]}"')
    if not antes["ip"]:
        comandos.append(
            f'/ip address add address="{objetos["ip"]}" '
            f'interface="{objetos["bridge"]}" comment="{objetos["comentario"]}"')

    if not comandos:
        return {"cambio": "sin cambios", **objetos}

    conexion.send_config_set(comandos)

    despues = consultar_loopback(conexion, objetos)
    if not (despues["bridge"] and despues["ip"]):
        raise RuntimeError(f"El cambio no quedó aplicado en el router: {despues}")
    return {"cambio": "creado", "comandos": comandos, **objetos}


def limpiar_loopback(conexion, estudiante):
    """Borra solo mis objetos (la IP 10.253.0.<N>/32 y el bridge lo-ssh-<N>).

    Igual que al crear: consulta, borra solo lo que exista y verifica.
    Los find llevan el nombre y la IP exactos, así nunca se borra nada ajeno.
    """
    objetos = objetos_propios(estudiante)
    antes = consultar_loopback(conexion, objetos)

    comandos = []
    # Primero la IP y después el bridge al que está asignada
    if antes["ip"]:
        comandos.append(
            f'/ip address remove [find where address="{objetos["ip"]}" '
            f'and interface="{objetos["bridge"]}"]')
    if antes["bridge"]:
        comandos.append(
            f'/interface bridge remove [find where name="{objetos["bridge"]}"]')

    if not comandos:
        return {"cambio": "sin cambios (no había nada que borrar)", **objetos}

    conexion.send_config_set(comandos)

    despues = consultar_loopback(conexion, objetos)
    if despues["bridge"] or despues["ip"]:
        raise RuntimeError(f"No se pudieron borrar mis objetos: {despues}")
    return {"cambio": "eliminado", "comandos": comandos, **objetos}


def recolectar_estado(conexion, device_type):
    """Manda los comandos de lectura del device_type y devuelve un dict."""
    comandos = COMANDOS_ESTADO.get(device_type)
    if comandos is None:
        raise ValueError(f"No tengo comandos definidos para {device_type}")

    estado = {}
    for dato, (comando, procesar) in comandos.items():
        salida = conexion.send_command(comando)
        estado[dato] = procesar(salida)
    return estado


def conectar_equipo(equipo, clave, estudiante=None, limpiar=False):
    """Se conecta por SSH a un equipo y devuelve un diccionario con el resultado.

    Si el equipo es un MikroTik con rol escritura y se conoce el estudiante,
    además asegura la loopback lo-ssh-<N> (o la borra si limpiar=True).

    Los errores se atrapan aquí mismo, por equipo: si uno falla se anota el
    mensaje en "estado" y el ciclo de main() sigue con los demás.
    """
    resultado = {
        "nombre": equipo["nombre"],
        "host": equipo["host"],
        "device_type": equipo["device_type"],
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "estado": "ok",
    }

    parametros = {
        "device_type": equipo["device_type"],
        "host": equipo["host"],
        "username": equipo["usuario"],
        "password": clave,
        "port": equipo.get("puerto", 22),
        # Un log por equipo con todo lo que se envió y recibió en la sesión
        "session_log": os.path.join(CARPETA_LOGS, f"{equipo['nombre']}.log"),
        "conn_timeout": 15,
    }

    try:
        # with = la sesión se cierra siempre, aunque haya un error adentro
        with ConnectHandler(**parametros) as conexion:
            resultado["prompt"] = conexion.find_prompt()
            resultado.update(recolectar_estado(conexion, equipo["device_type"]))
            # Un usuario de solo lectura en Cisco puede no ver el running-config;
            # en ese caso el nombre se saca del prompt (R-Cisco> o R-Cisco#)
            if not resultado["identidad"]:
                resultado["identidad"] = resultado["prompt"].rstrip("#>")

            if (equipo["rol"] == "escritura" and estudiante
                    and equipo["device_type"] == "mikrotik_routeros"):
                if limpiar:
                    resultado["configuracion"] = limpiar_loopback(conexion, estudiante)
                else:
                    resultado["configuracion"] = asegurar_loopback(conexion, estudiante)
    # De lo más específico a lo más general
    except NetmikoTimeoutException:
        resultado["estado"] = "error: timeout, no hubo respuesta del equipo (IP, SSH o red)"
    except NetmikoAuthenticationException:
        resultado["estado"] = f"error: autenticación, usuario o clave de '{equipo['usuario']}' incorrectos"
    except Exception as error:
        resultado["estado"] = f"error: {type(error).__name__}: {error}"

    return resultado


def guardar_reporte(resultados, ruta):
    """Guarda la lista de resultados en un JSON legible."""
    reporte = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "equipos": resultados,
    }
    with open(ruta, "w", encoding="utf-8") as archivo:
        # ensure_ascii=False para que las tildes se vean bien en el archivo
        json.dump(reporte, archivo, indent=2, ensure_ascii=False)


def imprimir_tabla(resultados):
    """Resumen en consola: equipo, IP, estado, interfaces y gateway."""
    encabezado = ["Equipo", "IP", "Estado", "Interfaces", "Gateway"]
    filas = []
    for r in resultados:
        if r["estado"] == "ok":
            filas.append([r["nombre"], r["host"], "ok",
                          str(len(r["interfaces"])), r["gateway"] or "-"])
        else:
            # El error completo ya va en el JSON, aquí solo una versión corta
            estado = r["estado"].split(",")[0][:40]
            filas.append([r["nombre"], r["host"], estado, "-", "-"])

    # El ancho de cada columna es el del texto más largo que tenga
    anchos = [max(len(fila[i]) for fila in [encabezado] + filas)
              for i in range(len(encabezado))]
    separador = "+".join("-" * (ancho + 2) for ancho in anchos)

    def formato(fila):
        return "|".join(f" {valor:<{ancho}} " for valor, ancho in zip(fila, anchos))

    print()
    print(formato(encabezado))
    print(separador)
    for fila in filas:
        print(formato(fila))


def leer_argumentos():
    parser = argparse.ArgumentParser(
        description="Lab 1: estado de los equipos y loopback propia en el MikroTik")
    parser.add_argument(
        "--limpiar", action="store_true",
        help="borra solo mis objetos (lo-ssh-<N> y 10.253.0.<N>/32) en vez de crearlos")
    return parser.parse_args()


def main():
    argumentos = leer_argumentos()

    try:
        equipos = cargar_inventario(ARCHIVO_INVENTARIO)
        estudiante = cargar_estudiante(ARCHIVO_INVENTARIO)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[ERROR] No pude leer el inventario: {error}")
        sys.exit(1)

    if estudiante is None:
        print("[AVISO] Falta 'estudiante' (numero_lista y nombre) en el inventario: "
              "no se va a tocar la configuración de ningún equipo.")
    elif argumentos.limpiar:
        print(f"Modo --limpiar: se borran solo lo-ssh-{estudiante['numero_lista']} "
              f"y 10.253.0.{estudiante['numero_lista']}/32.")

    os.makedirs(CARPETA_LOGS, exist_ok=True)

    resultados = []
    for equipo in equipos:
        print(f"Conectando a {equipo['nombre']} ({equipo['host']})...")
        clave = obtener_clave(equipo)
        resultado = conectar_equipo(equipo, clave, estudiante, argumentos.limpiar)
        resultados.append(resultado)

        if resultado["estado"] == "ok":
            print(f"  [OK] {resultado['identidad']} - {len(resultado['interfaces'])} "
                  f"interfaces, gateway {resultado['gateway'] or '(ninguno)'}")
            if "configuracion" in resultado:
                config = resultado["configuracion"]
                print(f"  Configuración {config['bridge']} ({config['ip']}): {config['cambio']}")
        else:
            print(f"  [FALLO] {resultado['estado']}")

    guardar_reporte(resultados, ARCHIVO_REPORTE)
    imprimir_tabla(resultados)

    correctos = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\nListo: {correctos} de {len(resultados)} equipos conectados.")
    print(f"Reporte guardado en {ARCHIVO_REPORTE}")


if __name__ == "__main__":
    main()
