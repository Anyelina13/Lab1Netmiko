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

ARCHIVO_INVENTARIO = "inventario.yaml"

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


def main():
    try:
        equipos = cargar_inventario(ARCHIVO_INVENTARIO)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[ERROR] No pude leer el inventario: {error}")
        sys.exit(1)

    print(f"Equipos en el inventario: {len(equipos)}")
    for equipo in equipos:
        clave = obtener_clave(equipo)
        # La clave nunca se imprime, solo se confirma que ya se tiene
        estado_clave = "lista" if clave else "vacía"
        print(
            f"  - {equipo['nombre']} ({equipo['host']}) "
            f"{equipo['device_type']} usuario={equipo['usuario']} "
            f"rol={equipo['rol']} clave={estado_clave}"
        )


if __name__ == "__main__":
    main()
