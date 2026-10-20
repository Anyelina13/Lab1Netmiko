# Laboratorio 1 - Inventario, estado y configuración segura con Netmiko

Curso ITIEL-13 Redes Programables (Grupo 01), III periodo 2026.

El script lee los equipos desde `inventario.yaml`, se conecta a cada uno por SSH
con Netmiko, recolecta su estado como datos estructurados y lo guarda en
`reporte_estado.json`. En el MikroTik (rol `escritura`) además deja creada una
loopback propia sin duplicar nada. El registro de cada sesión queda en `logs/`.

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

Al inicio del archivo va el bloque `estudiante`, con el número de lista N y el
nombre. Se usa para armar los objetos propios en el MikroTik:

```yaml
estudiante:
  numero_lista: 7
  nombre: Mi Nombre
```

Si el bloque está vacío, el script solo consulta y no cambia la configuración
de ningún equipo.

## Variables de entorno (contraseñas)

La contraseña de cada equipo se toma de una variable `LAB_PASS_<NOMBRE>`, con
el nombre del equipo en mayúsculas y los guiones cambiados por `_`:

```bash
export LAB_PASS_MT_LAB='clave-del-mikrotik'
export LAB_PASS_CISCO_LAB='clave-del-cisco'
```

Si la variable no existe, el script pide la clave al ejecutarse (no se muestra
en pantalla).

## Ejecución

```bash
source env/bin/activate
python lab1_inventario.py
```

El script recorre todos los equipos del inventario. Si alguno no responde o la
clave es incorrecta, muestra el error de ese equipo y continúa con los demás.
En `logs/` queda un archivo por equipo (`logs/mt-lab.log`) con la sesión SSH.

Para probar el manejo de errores sin tocar el inventario:

```bash
export LAB_PASS_MT_LAB=mala
python lab1_inventario.py
```

Para borrar lo que el script creó en el MikroTik (solo mis objetos):

```bash
python lab1_inventario.py --limpiar
```

## Qué hace con cada equipo

**Estado (solo lectura).** Los comandos están en el diccionario
`COMANDOS_ESTADO`, agrupados por `device_type`. Para el MikroTik se consulta:

| Dato | Comando |
|---|---|
| Nombre del equipo | `/system identity print` |
| Tiempo encendido y versión | `/system resource print` |
| Interfaces con IP | `/ip address print terse` |
| Ruta por defecto | `/ip route print terse where dst-address=0.0.0.0/0` |

Cada salida se convierte en diccionario o lista antes de guardarla.

**Extra multivendor (Cisco IOS).** El Cisco (`cisco-lab`, 10.60.30.203) está en
el inventario con `rol: lectura`, así que solo se consulta. Sus comandos son
otra entrada del mismo diccionario `COMANDOS_ESTADO`, sin ningún `if` por
equipo:

| Dato | Comando |
|---|---|
| Nombre del equipo | `show running-config \| include hostname` |
| Tiempo encendido | `show version \| include uptime` |
| Interfaces con IP | `show ip interface brief` |
| Ruta por defecto | `show ip route 0.0.0.0` |

Si el usuario de solo lectura no puede ver el running-config, el nombre se
toma del prompt.

**Reporte.** Al terminar se genera `reporte_estado.json`, con la fecha/hora y
el estado de cada equipo (`ok` o el mensaje de error), y se imprime una tabla
con equipo, IP, estado, cantidad de interfaces y gateway.

**Cambio de configuración (solo `rol: escritura`).** Se asegura el bridge
`lo-ssh-<N>` con la IP `10.253.0.<N>/32` y un comentario con el nombre. Primero
se consulta si existe y solo se crea lo que falta; después se vuelve a
consultar para verificar. En una segunda ejecución sale `sin cambios`. Las
consultas filtran por el nombre exacto, así que no se tocan objetos de otros
estudiantes.

Con `--limpiar` pasa lo contrario: se consulta, se borran solo la IP
`10.253.0.<N>/32` y el bridge `lo-ssh-<N>` (si existen) y se verifica que ya no
estén. Si no había nada, sale `sin cambios`.

## Uso de IA

Usé Claude (asistente de IA de Anthropic) como apoyo para armar la estructura
del proyecto, escribir y revisar partes del script y redactar este README.
