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

## Uso de IA

Usé Claude (asistente de IA de Anthropic) como apoyo para armar la estructura
del proyecto, escribir y revisar partes del script y redactar este README.
