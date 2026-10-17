# Cómo poner a funcionar a Aries

Guía para armar el cerebro de Aries en tu PC y conectarle el robot con el micrófono.
Al final tienes una tabla de problemas comunes y cómo resolverlos.

## Qué necesitas

- Una PC con **Ubuntu** y **tarjeta gráfica NVIDIA** (con 8 GB va sobrado).
- Internet para la instalación (después solo hace falta para el clima).
- El circuito: ESP32 en la protoboard, micrófono INMP441 y relé.
- Un cable USB **de datos** (algunos cables solo cargan, y con esos la PC no ve el ESP32).
- El parlante Bluetooth, **emparejado con tu PC** (Configuración → Bluetooth).

## 1. Bajar el proyecto

```
git clone https://github.com/Deividmart/Prototype-Robot.git
cd Prototype-Robot/robot-ia
```

## 2. Instalar todo

```
bash setup.sh
```

Instala Ollama con Gemma 3 4B, Whisper, las voces y las herramientas del ESP32. Tarda entre
20 y 40 minutos (descarga varios GB) y te pide tu contraseña. Si se corta, vuelve a correrlo:
lo que ya instaló se salta.

**Cuando termine, cierra sesión y vuelve a entrar** (o reinicia). Si no, el puerto USB del
ESP32 no va a funcionar.

## 3. Conectar el micrófono

⚠️ **Siempre con el USB desenchufado** mientras conectas cables.

El ESP32 tapa todos los agujeros de su lado izquierdo en la protoboard, así que todo va del
**lado derecho** (VIN, GND, D13, D27, D25, D33, D32). El pin 3V3 queda tapado: por eso el
micrófono se alimenta desde el **D27**, que el firmware pone en 3,3 V.

| Micrófono | Va a | Color de cable (punta en la protoboard) |
|---|---|---|
| VDD | D27 | negro |
| GND | fila 30 (columnas F a J) | marrón |
| L/R | fila 30 (columnas F a J) | blanco |
| WS | D25 | gris |
| SCK | D32 | morado |
| SD | D33 | amarillo |

La **fila 30** es la fila de tierra: ahí llega el GND del ESP32 (cable naranja) y de ahí sale
un cable a la patita `−` del relé (35 J).

El relé: `S` → D13, `+` → VIN, `−` → fila de tierra. Todavía no se usa, pero puede quedar conectado.

> Regla de la protoboard: dos cosas solo se conectan si están en el mismo grupito de 5
> agujeros (la misma fila y del mismo lado del canal del medio).

## 4. Configurar el WiFi

El ESP32 tiene que conectarse a la **misma red WiFi que tu PC**, y tiene que ser de
**2.4 GHz** (el ESP32 no se conecta a redes 5G).

Primero averigua la IP de tu PC:

```
hostname -I
```

Usa el primer número (por ejemplo `192.168.1.25`). Después crea el archivo con tus datos:

```
cd firmware/robot_wifi
cp secrets.h.example secrets.h
nano secrets.h
```

Cambia el nombre de la red, la contraseña y la IP del servidor:

```
#define WIFI_SSID "nombre_de_tu_red"
#define WIFI_PASSWORD "tu_contraseña"
#define SERVIDOR_URL "http://192.168.1.25:5000"
```

Guarda con **Ctrl+O** y Enter, y sal con **Ctrl+X**. Este archivo no se sube a GitHub.

## 5. Subir el firmware al ESP32

Enchufa el ESP32 por USB y, desde `firmware/robot_wifi`:

```
arduino-cli compile --fqbn esp32:esp32:esp32 .
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32 .
```

## 6. Encender el cerebro

En una terminal, desde la carpeta `robot-ia`:

```
bash iniciar.sh
```

Te pregunta qué micrófono usar: escribe **1** (el del robot) y presiona Enter. Espera a que diga
**"Gemma cargada en la GPU"**. Deja esta terminal abierta: si la cierras o presionas Ctrl+C, el
robot se queda sin cerebro.

## 7. Probar

Abre **otra terminal** (Ctrl+Alt+T) y abre el monitor del ESP32:

```
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

Presiona el botón **EN** del ESP32 para reiniciarlo y ver el arranque. Tienes que ver:

1. `Conectado. IP del ESP32: ...`: se conectó al WiFi.
2. `Micrófono OK: está mandando sonido.`: el micrófono está bien conectado.
3. `Conectado al servidor de Aries`: encontró el cerebro. En la otra terminal aparece `🤖 Robot conectado`.

Ahora habla cerca del micrófono: **"Hola Aries"**. Aries te contesta por el parlante, y en el
monitor aparece la respuesta. Después prueba "avanza dos metros" y "Aries, ¿qué clima hace?".

También puedes escribir comandos en el monitor (por ejemplo `hola aries`) y presionar Enter.

## 8. Calibrar el volumen del micrófono

En el monitor, escribe `nivel` y presiona Enter. Aparece una barra con el volumen:

```
 -24.3 dBFS |######################                  |
```

Habla normal a unos 30 cm del micrófono y mira el número mientras hablas:

| Mientras hablas marca | Qué hacer |
|---|---|
| Entre **-35 y -10** | Está bien, no toques nada |
| Menos de **-40** (muy bajo) | En `robot_wifi.ino`, baja `CORRIMIENTO` de 12 a 11 (cada 1 menos duplica el volumen) |
| Aparece **SATURA** | Sube `CORRIMIENTO` a 13 |

Después de cambiarlo, vuelve a subir el firmware (paso 5). Escribe `nivel` otra vez para ocultar
la barra. El servidor también muestra el volumen de cada frase que escucha (`🎚️ Frase del robot`)
y avisa si está muy bajo o satura.

## Plan B: si el micrófono del robot no funciona

Usa el micrófono de la computadora. **No hace falta tocar cables ni volver a subir el firmware.**

1. En la terminal del cerebro, presiona **Ctrl+C**.
2. Vuelve a encenderlo eligiendo la opción **2**:

   ```
   bash iniciar.sh
   ```

   (o directamente `bash iniciar.sh pc`)
3. Tiene que decir `🎤 Micrófono: el de la COMPUTADORA`.

Ahora le hablas a la computadora en lugar de al robot: "Hola Aries", "Aries, avanza dos metros".
El robot **sigue recibiendo las acciones** por WiFi y el parlante sigue hablando; solo cambia por
dónde te escucha. El audio que mande el micrófono del robot se ignora, así que aunque mande ruido
no molesta.

Usa el micrófono que Ubuntu tenga elegido como entrada. Para cambiarlo (por ejemplo, a un
headset): **Configuración → Sonido → Entrada**, antes de encender el cerebro.

Para volver al micrófono del robot: Ctrl+C y `bash iniciar.sh robot`.

## Problemas comunes

| Problema | Solución |
|---|---|
| No existe `/dev/ttyUSB0` | Prueba otro cable USB (el tuyo puede ser solo de carga) u otro puerto. Revisa con `lsusb` que aparezca "CP210x". |
| "Permission denied" en `/dev/ttyUSB0` | No cerraste sesión después de `setup.sh`. Cierra sesión y vuelve a entrar. |
| "port is busy" al subir el firmware | Tienes el monitor abierto. Ciérralo con Ctrl+C. |
| `AVISO: el micrófono no manda nada` | Revisa los 6 cables del micrófono con la tabla del paso 3, sobre todo VDD → D27. |
| `AVISO: ... siempre el mismo valor` | Revisa SD → D33 y que GND y L/R lleguen a la fila 30. |
| Nunca dice "Conectado al servidor" | El servidor no está corriendo, la IP de `secrets.h` está mal, o la PC y el ESP32 están en redes distintas. Si tienes firewall activo: `sudo ufw allow 5000/tcp`. |
| "No se pudo conectar" al WiFi | Revisa nombre y contraseña en `secrets.h`, y que la red sea de 2.4 GHz. |
| "CUDA out of memory" | Hay otro programa usando la tarjeta gráfica (juegos, otro `server.py` o `escucha.py`). Ciérralo. |
| Aries no se escucha | El parlante tiene que estar conectado a la PC **antes** de encender el cerebro (`bash iniciar.sh`). |
| El micrófono del robot no funciona y no hay tiempo de arreglarlo | Usa el [plan B](#plan-b-si-el-micrófono-del-robot-no-funciona): `bash iniciar.sh pc`. |
| Escucha pero no entiende | Mira el volumen (paso 8). Para revisar el audio que llega, enciende el cerebro con `bash iniciar.sh robot --guardar-audio`: cada frase se guarda en `grabaciones/` y la puedes escuchar con `pw-play`. |

## Cómo funciona (resumen)

El ESP32 manda el audio del micrófono por WiFi a la PC. En la PC, un detector separa la voz del
silencio, Whisper la pasa a texto, y si la frase dice "Aries", Gemma 3 4B decide la acción. La
acción vuelve al ESP32 (los motores por ahora se muestran como `>> MOTORES: ...`) y Piper dice la
respuesta por el parlante Bluetooth. Si se corta la conexión con la PC, el ESP32 frena por
seguridad.
