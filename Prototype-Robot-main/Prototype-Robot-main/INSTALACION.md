# Cómo poner a funcionar a Aries

Guía para armar el cerebro de Aries en tu PC con **Windows** y conectarle el robot con el
micrófono. Se hace una sola vez. Para el uso de todos los días, mira [USO.md](USO.md).

Al final hay una tabla de [problemas comunes](#problemas-comunes) y lo que cambia
[si usas Ubuntu](#si-usas-ubuntu).

## Qué necesitas

- Una PC con **Windows 10 u 11** y **tarjeta gráfica NVIDIA** (con 8 GB va sobrado), con el
  driver de NVIDIA instalado.
- Unos **15 GB libres** en el disco e internet para la instalación (después solo hace falta para el clima).
- El circuito: ESP32 en la protoboard, micrófono INMP441 y relé.
- Un cable USB **de datos** (algunos cables solo cargan, y con esos la PC no ve el ESP32).
- El parlante Bluetooth, **emparejado con la PC**: Configuración → Bluetooth y dispositivos.
  Fíjate que quede como salida de sonido: Configuración → Sistema → Sonido → Salida.

## 1. Bajar el proyecto

1. Entra a <https://github.com/Deividmart/Prototype-Robot> (si el repositorio es privado, David
   te tiene que agregar como colaborador).
2. Botón verde **Code** → **Download ZIP**.
3. Descomprime el ZIP (clic derecho → **Extraer todo**), por ejemplo en `Documentos`.

Te queda una carpeta `Prototype-Robot-main`. Adentro está la carpeta **`robot-ia`**: ahí
pasa todo.

> **Cómo abrir una terminal en una carpeta:** abre la carpeta en el Explorador de archivos,
> haz clic derecho en un espacio vacío y elige **Abrir en Terminal**. Todos los comandos de
> esta guía se escriben ahí.

## 2. Instalar todo

En la carpeta `robot-ia`, haz **doble clic en `instalar.bat`**.

Instala Python, Ollama con Gemma 3 4B, Whisper con soporte para la tarjeta gráfica, las voces,
ffmpeg y las herramientas del ESP32. Tarda entre 20 y 40 minutos (descarga unos 10 GB).

- Si Windows pregunta **"¿Quieres permitir que esta aplicación haga cambios?"**, acepta. Al
  final lo pide para abrir el puerto 5000 del firewall, que es por donde el ESP32 le habla al cerebro.
- Si se corta o falla un paso, vuelve a hacer doble clic en `instalar.bat`: lo que ya instaló se salta.

**Cuando termine, cierra todas las terminales** y abre una nueva para seguir.

## 3. Armar el robot y conectar el micrófono

⚠️ **Siempre con el USB desenchufado** mientras conectas cables.

Cómo montar todo en el chasis y dónde va cada componente (ESP32 entre dos protoboards, motores,
encoders, MPU6050, INA219, pilas): **[ENSAMBLAJE.md](ENSAMBLAJE.md)**.

El micrófono, para tenerlo a mano. Se alimenta desde el **D27**, que el firmware pone en 3,3 V:

| Micrófono | Va a |
|---|---|
| VDD | D27 |
| GND | riel de GND |
| L/R | riel de GND |
| WS | D25 |
| SCK | D32 |
| SD | D33 |

El relé ya no se usa: quítalo (el TB6612 se encarga de los motores).

> Regla de la protoboard: dos cosas solo se conectan si están en el mismo grupito de 5
> agujeros (la misma fila y del mismo lado del canal del medio).

## 4. Configurar el WiFi

El ESP32 tiene que conectarse a la **misma red WiFi que la PC**, y tiene que ser de
**2.4 GHz** (el ESP32 no se conecta a redes 5G).

Primero averigua la IP de la PC. En una terminal:

```
ipconfig
```

Busca el adaptador con el que la PC está conectada (**Wi-Fi** o **Ethernet**) y copia la
**Dirección IPv4** (por ejemplo `192.168.1.25`).

Después, en una terminal abierta en la carpeta `robot-ia\firmware\robot_wifi`:

```
copy secrets.h.example secrets.h
notepad secrets.h
```

Se abre el Bloc de notas. Cambia el nombre de la red, la contraseña y la IP de la PC:

```
#define WIFI_SSID "nombre_de_tu_red"
#define WIFI_PASSWORD "tu_contraseña"
#define SERVIDOR_URL "http://192.168.1.25:5000"
```

Guarda con **Ctrl+S** y cierra. Este archivo no se sube a GitHub.

Además, la red de la PC tiene que estar marcada como **privada**: Configuración → Red e
Internet → Wi-Fi (o Ethernet) → tu red → **Red privada**.

## 5. Subir el firmware al ESP32

Enchufa el ESP32 por USB. Averigua en qué puerto quedó:

```
arduino-cli board list
```

Busca la línea que dice **Serial Port (USB)** y anota el puerto: `COM3`, `COM4`, etc. En esta
guía usamos `COM3`; cámbialo por el tuyo.

Desde la carpeta `robot-ia\firmware\robot_wifi`:

```
arduino-cli compile --fqbn esp32:esp32:esp32 .
arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32 .
```

## 6. Encender el cerebro

En la carpeta `robot-ia`, haz **doble clic en `iniciar.bat`** (o escribe `.\iniciar.bat` en una
terminal abierta ahí).

Te pregunta qué micrófono usar: escribe **1** (el del robot) y presiona Enter. Espera a que diga
**"Gemma cargada en la GPU"**. Deja esa ventana abierta: si la cierras o presionas Ctrl+C, el
robot se queda sin cerebro.

Si Windows pregunta si quieres permitir que **Python** acceda a la red, marca **Redes
privadas** y acepta.

## 7. Probar

Abre **otra terminal** y abre el monitor del ESP32 (con tu puerto):

```
arduino-cli monitor -p COM3 -c baudrate=115200
```

Presiona el botón **EN** del ESP32 para reiniciarlo y ver el arranque. Tienes que ver:

1. `Conectado. IP del ESP32: ...`: se conectó al WiFi.
2. `Micrófono OK: está mandando sonido.`: el micrófono está bien conectado.
3. `Conectado al servidor de Aries`: encontró el cerebro. En la ventana del cerebro aparece `🤖 Robot conectado`.

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

`robot_wifi.ino` se puede editar con el Bloc de notas (`notepad robot_wifi.ino`). Después de
cambiarlo, cierra el monitor y vuelve a subir el firmware (paso 5). Escribe `nivel` otra vez
para ocultar la barra. El cerebro también muestra el volumen de cada frase que escucha
(`🎚️ Frase del robot`) y avisa si está muy bajo o satura.

## Plan B: si el micrófono del robot no funciona

Usa el micrófono de la computadora. **No hace falta tocar cables ni volver a subir el firmware.**

1. En la ventana del cerebro, presiona **Ctrl+C** (si pregunta "¿Desea terminar el trabajo por
   lotes?", escribe **S**).
2. Vuelve a abrir `iniciar.bat` y elige la opción **2** (o escribe `.\iniciar.bat pc`).
3. Tiene que decir `🎤 Micrófono: el de la COMPUTADORA`.

Ahora le hablas a la computadora en lugar de al robot: "Hola Aries", "Aries, avanza dos metros".
El robot **sigue recibiendo las acciones** por WiFi y el parlante sigue hablando; solo cambia por
dónde te escucha. El audio que mande el micrófono del robot se ignora, así que aunque mande ruido
no molesta.

Se usa el micrófono que Windows tenga elegido. Para cambiarlo (por ejemplo, a un headset):
**Configuración → Sistema → Sonido → Entrada**, antes de encender el cerebro.

Para volver al micrófono del robot: Ctrl+C y `.\iniciar.bat robot`.

## Problemas comunes

| Problema | Solución |
|---|---|
| `arduino-cli board list` no muestra ningún puerto | Prueba otro cable USB (el tuyo puede ser solo de carga) u otro puerto. Si sigue sin aparecer, instala el driver **CP210x Universal Windows Driver** de Silicon Labs (<https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers>) y vuelve a enchufar el ESP32. |
| "Access denied" o "port is busy" al subir el firmware | Tienes el monitor abierto en otra terminal (u otro programa usando el puerto, como Arduino IDE). Ciérralo. |
| `instalar.bat` dice que no encuentra winget | Instala **Instalador de aplicación** desde la Microsoft Store y vuelve a correrlo. |
| `instalar.bat` dice que no encuentra el driver de NVIDIA | Instálalo desde <https://www.nvidia.com/drivers>, reinicia y vuelve a correrlo. |
| Dice "no encuentro ..." después de instalarlo | Cierra la ventana y vuelve a hacer doble clic en `instalar.bat`. |
| `"arduino-cli" no se reconoce como un comando` | Cierra la terminal y abre una nueva (los programas recién instalados aparecen en terminales nuevas). |
| `AVISO: el micrófono no manda nada` | Revisa los 6 cables del micrófono con la tabla del paso 3, sobre todo VDD → D27. |
| `AVISO: ... siempre el mismo valor` | Revisa SD → D33 y que GND y L/R lleguen a la fila 30. |
| Nunca dice "Conectado al servidor" | El cerebro no está encendido, la IP de `secrets.h` está mal, la PC y el ESP32 están en redes distintas, o la red de la PC no está como **privada** (paso 4). |
| "No se pudo conectar" al WiFi | Revisa nombre y contraseña en `secrets.h`, y que la red sea de 2.4 GHz. |
| "CUDA out of memory" | Hay otro programa usando la tarjeta gráfica (un juego u otra ventana de `iniciar.bat`). Ciérralo. |
| Aries no se escucha | El parlante tiene que estar conectado y elegido como salida de sonido **antes** de encender el cerebro. |
| Tarda varios segundos en responder | PyTorch no está usando la tarjeta gráfica. Vuelve a correr `instalar.bat` y fíjate en el paso 5: tiene que decir "Whisper va a usar la tarjeta grafica: NVIDIA ...". |
| El micrófono del robot no funciona y no hay tiempo de arreglarlo | Usa el [plan B](#plan-b-si-el-micrófono-del-robot-no-funciona): `.\iniciar.bat pc`. |
| Escucha pero no entiende | Mira el volumen (paso 8). Para revisar el audio que llega, enciende el cerebro con `.\iniciar.bat robot --guardar-audio`: cada frase se guarda en la carpeta `grabaciones` y la puedes escuchar con doble clic. |

## Si usas Ubuntu

Todo funciona igual; cambian estos comandos:

| Paso | En Ubuntu |
|---|---|
| 1. Bajar el proyecto | `git clone https://github.com/Deividmart/Prototype-Robot.git` |
| 2. Instalar | `bash setup.sh` desde `robot-ia` (pide tu contraseña). Al terminar, **cierra sesión y vuelve a entrar** para poder usar el puerto USB. |
| 4. IP de la PC | `hostname -I` (el primer número). Para editar: `cp secrets.h.example secrets.h` y `nano secrets.h` (guardar: Ctrl+O, salir: Ctrl+X). |
| 5 y 7. Puerto del ESP32 | `/dev/ttyUSB0` en lugar de `COM3`. |
| 6. Encender el cerebro | `bash iniciar.sh` (o `bash iniciar.sh robot` / `bash iniciar.sh pc`). |
| Firewall | Si usas `ufw`: `sudo ufw allow 5000/tcp`. |
| No aparece `/dev/ttyUSB0` | Revisa con `lsusb` que aparezca "CP210x"; si no, cambia el cable. |
| "Permission denied" en el puerto | No cerraste sesión después de `setup.sh`. |
| Escuchar grabaciones | `pw-play grabaciones/frase_123456.wav` |

## Cómo funciona (resumen)

El ESP32 manda el audio del micrófono por WiFi a la PC. En la PC, un detector separa la voz del
silencio, Whisper la pasa a texto, y si la frase dice "Aries", Gemma 3 4B decide la acción. La
acción vuelve al ESP32 (los motores por ahora se muestran como `>> MOTORES: ...`) y Piper dice la
respuesta por el parlante Bluetooth. Si se corta la conexión con la PC, el ESP32 frena por
seguridad.
