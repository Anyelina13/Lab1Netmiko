"""
ITIEL-13 Redes Programables - Laboratorio 1
Inventario, estado y configuración segura con Python + SSH (Netmiko).

Uso:
    export LAB_PASS_MT_LAB='la-clave'     # opcional, si no existe se pide
    python lab1_inventario.py
"""

import os
import sys
import getpass

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)

ARCHIVO_INVENTARIO = "inventario.yaml"
CARPETA_LOGS = "logs"

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


def conectar_equipo(equipo, clave):
    """Se conecta por SSH a un equipo y devuelve un diccionario con el resultado.

    Los errores se atrapan aquí mismo, por equipo: si uno falla se anota el
    mensaje en "estado" y el ciclo de main() sigue con los demás.
    """
    resultado = {
        "nombre": equipo["nombre"],
        "host": equipo["host"],
        "device_type": equipo["device_type"],
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
    # De lo más específico a lo más general
    except NetmikoTimeoutException:
        resultado["estado"] = "error: timeout, no hubo respuesta del equipo (IP, SSH o red)"
    except NetmikoAuthenticationException:
        resultado["estado"] = f"error: autenticación, usuario o clave de '{equipo['usuario']}' incorrectos"
    except Exception as error:
        resultado["estado"] = f"error: {type(error).__name__}: {error}"

    return resultado


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
            print(f"  [OK] Conectado. Prompt: {resultado['prompt']}")
        else:
            print(f"  [FALLO] {resultado['estado']}")

    correctos = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\nListo: {correctos} de {len(resultados)} equipos conectados.")


if __name__ == "__main__":
    main()
