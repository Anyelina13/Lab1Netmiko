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

`requirements.txt` fija `paramiko<4` porque el Cisco IOS 12.4 solo acepta
algoritmos SSH con SHA-1 (`diffie-hellman-group14-sha1`), que paramiko 4 ya
no trae.

## Mi laboratorio (GNS3 local)

La ejecución de `reporte_estado.json` y `logs/` se hizo en mi propia
topología de GNS3, armada igual que la del enunciado:

| Equipo | IP | Usuario |
|---|---|---|
| MikroTik CHR 7.18.2 (`ether2`) | 10.60.30.202/24 | `lab-ssh` (grupo con lectura/escritura y rest-api) |
| Cisco c7200 IOS 12.4 (`Gi1/0`) | 10.60.30.203/24 | `lab-ssh` (privilegio 1, solo lectura) |
| Mi Linux (interfaz `tap-lab`, nube "Internet") | 10.60.30.1/24 | — |

La interfaz `tap-lab` se crea en el Linux antes de abrir el proyecto (se
pierde al reiniciar):

```bash
sudo ip tuntap add dev tap-lab mode tap user $USER
sudo ip addr add 10.60.30.1/24 dev tap-lab
sudo ip link set tap-lab up
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

**Extra REST (SSH vs. REST).** Para el MikroTik, si la conexión SSH funcionó,
el script vuelve a pedir los mismos datos por la API REST
(`https://10.60.30.202/rest`, con `requests` y el mismo usuario y clave):
`/system/identity`, `/system/resource`, `/ip/address` y `/ip/route`. En el
reporte, dentro de `rest`, quedan los datos obtenidos y una `comparacion` dato
por dato (`identidad`, `version`, `interfaces`, `gateway`) con el valor por SSH,
el valor por REST y si coinciden. El uptime no se compara porque cambia entre
una consulta y otra, y la IP de mi loopback tampoco, porque SSH la lee antes
de crearla o borrarla. Si REST falla, se anota el error ahí sin afectar el
estado SSH del equipo. El certificado del router es autofirmado, por eso se
usa `verify=False`.

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

## Ejemplo del reporte

Estructura de `reporte_estado.json` (valores de ejemplo):

```json
{
  "generado": "2026-10-20T18:05:12",
  "equipos": [
    {
      "nombre": "mt-lab",
      "host": "10.60.30.202",
      "device_type": "mikrotik_routeros",
      "fecha": "2026-10-20T18:05:03",
      "estado": "ok",
      "identidad": "MikroTik",
      "recursos": {"uptime": "3h2m10s", "version": "7.16 (stable)"},
      "interfaces": [{"interfaz": "ether1", "ip": "10.60.30.202/24", "deshabilitada": false}],
      "gateway": "10.60.30.1",
      "configuracion": {"cambio": "sin cambios", "bridge": "lo-ssh-7", "ip": "10.253.0.7/32"},
      "rest": {"estado": "ok", "datos": {}, "comparacion": {"todo_coincide": true}}
    },
    {
      "nombre": "cisco-lab",
      "host": "10.60.30.203",
      "estado": "error: autenticación, usuario o clave de 'lab-ssh' incorrectos"
    }
  ]
}
```

## Uso de IA

Usé Claude (asistente de IA de Anthropic) como apoyo para armar la estructura
del proyecto, escribir y revisar partes del script y redactar este README.
