# Laboratorio 1 - Inventario, estado y configuración segura con Netmiko

Curso ITIEL-13 Redes Programables (Grupo 01), III periodo 2026.

El script lee los equipos desde `inventario.yaml`, se conecta a cada uno por SSH
con Netmiko y guarda el registro de la sesión en la carpeta `logs/`.

## Instalación

```bash
git clone <url-del-repositorio>
cd Lab1Netmico
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

## Inventario

Los equipos están en `inventario.yaml`. Cada uno lleva `nombre`, `host`,
`device_type`, `usuario` y `rol` (`lectura` o `escritura`). El archivo no
contiene contraseñas.

## Variables de entorno (contraseñas)

La contraseña de cada equipo se toma de una variable `LAB_PASS_<NOMBRE>`, con
el nombre del equipo en mayúsculas y los guiones cambiados por `_`:

```bash
export LAB_PASS_MT_LAB='clave-del-mikrotik'
```

Si la variable no existe, el script pide la clave al ejecutarse (no se muestra
en pantalla).

## Ejecución

```bash
source env/bin/activate
python lab1_inventario.py
```

## Uso de IA

Usé Claude (asistente de IA de Anthropic) como apoyo para armar la estructura
del proyecto, escribir y revisar partes del script y redactar este README.
