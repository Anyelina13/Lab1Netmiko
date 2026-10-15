"""
ITIEL-13 Redes Programables - Laboratorio 1
Inventario, estado y configuración segura con Python + SSH (Netmiko).

Uso:
    export LAB_PASS_MT_LAB='la-clave'     # opcional, si no existe se pide
    python lab1_inventario.py
"""

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
}


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


def conectar_equipo(equipo, clave):
    """Se conecta por SSH a un equipo y devuelve un diccionario con el resultado.

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


def main():
    try:
        equipos = cargar_inventario(ARCHIVO_INVENTARIO)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[ERROR] No pude leer el inventario: {error}")
        sys.exit(1)

    os.makedirs(CARPETA_LOGS, exist_ok=True)

    resultados = []
    for equipo in equipos:
        print(f"Conectando a {equipo['nombre']} ({equipo['host']})...")
        clave = obtener_clave(equipo)
        resultado = conectar_equipo(equipo, clave)
        resultados.append(resultado)

        if resultado["estado"] == "ok":
            print(f"  [OK] {resultado['identidad']} - {len(resultado['interfaces'])} "
                  f"interfaces, gateway {resultado['gateway'] or '(ninguno)'}")
        else:
            print(f"  [FALLO] {resultado['estado']}")

    guardar_reporte(resultados, ARCHIVO_REPORTE)

    correctos = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\nListo: {correctos} de {len(resultados)} equipos conectados.")
    print(f"Reporte guardado en {ARCHIVO_REPORTE}")


if __name__ == "__main__":
    main()
