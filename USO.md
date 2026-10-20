# Usar a Aries

Guía para cada vez que van a usar el robot: cómo encenderlo, qué decirle y qué significa lo que
aparece en pantalla. Para instalar, conectar los cables o configurar el WiFi por primera vez,
mira [INSTALACION.md](INSTALACION.md).

## Antes de empezar

- [ ] El parlante Bluetooth está **encendido, conectado a la PC y elegido como salida de sonido**.
- [ ] El ESP32 está **enchufado por USB** (o alimentado por batería, si ya está montado en el robot).
- [ ] La PC y el ESP32 están en la **misma red WiFi**.

## 1. Encender el cerebro (ventana 1)

En la carpeta `robot-ia`, haz **doble clic en `iniciar.bat`** (o, en una terminal abierta en esa
carpeta, escribe `.\iniciar.bat`). Elige el micrófono:

- **1**: el del robot (lo normal).
- **2**: el de la computadora (si el del robot no funciona; ver [Cambiar de micrófono](#cambiar-de-micrófono)).

Espera a ver estas líneas. Tarda unos 15 segundos la primera vez:

```
Gemma cargada en la GPU
🎤 Micrófono: el del ROBOT
 * Running on http://192.168.x.x:5000
```

**No cierres esta ventana ni presiones Ctrl+C**: es el cerebro del robot.

## 2. Ver al robot (ventana 2)

Abre una terminal (clic derecho en el botón de Inicio → **Terminal**) y abre el monitor. `COM3`
es el puerto del ESP32; si no sabes cuál es el tuyo, escribe `arduino-cli board list`.

```
arduino-cli monitor -p COM3 -c baudrate=115200
```

Presiona el botón **EN** del ESP32 para ver el arranque completo. Si todo está bien aparece:

```
Conectado. IP del ESP32: 192.168.x.x
Micrófono OK: está mandando sonido. Escribe "nivel" para ver el volumen.
Conectado al servidor de Aries
```

Y en la ventana 1 aparece `🤖 Robot conectado`. Ya puedes hablarle.

## 3. Hablarle a Aries

Aries solo reacciona si escucha su nombre. Hay dos formas:

- **Todo junto:** "Aries, avanza dos metros".
- **En dos pasos:** "Hola Aries" → te saluda → durante **8 segundos** te escucha sin que repitas el nombre: "avanza dos metros".

Mientras Aries habla no escucha: espera a que termine. Si dices algo sin "Aries" y ya pasaron los 8
segundos, lo ignora a propósito (así no reacciona a las conversaciones de alrededor).

### Lo que entiende

Entiende **español e inglés** y contesta en el idioma en que le hablaste.

| Para... | Puedes decir | El robot hace |
|---|---|---|
| Saludar | "Hola Aries", "buenos días", "Hi Aries", "¿cómo estás?" | Se presenta y ofrece ayuda |
| Avanzar | "avanza dos metros", "move forward one meter" | `>> MOTORES: avanzar 2.0 m` |
| Retroceder | "retrocede un metro", "go back two meters" | `>> MOTORES: retroceder 1.0 m` |
| Girar | "gira a la derecha 45 grados", "turn left", "date media vuelta" | `>> MOTORES: girar 45 grados (derecha)` |
| Frenar | "para", "detente", "quieto", "stop" | `>> MOTORES: detener` |
| El clima | "¿qué clima hace?", "¿va a llover?", "how's the weather?" | Dice el clima real de Barranquilla (necesita internet) |

- Sin número, **avanza o retrocede 1 metro** y **gira 90 grados**.
- Si le pides algo que no sabe hacer (un chiste, por ejemplo), dice "Perdón, no entendí" y no se mueve.

### Escribirle en vez de hablarle

En la ventana 2 (el monitor) escribe el comando y presiona Enter, por ejemplo `avanza un metro`.
Escribiendo no hace falta decir "Aries".

## Qué significa lo que aparece

**Ventana 1 (el cerebro):**

| Línea | Qué significa |
|---|---|
| `🤖 Robot conectado` / `🔌 Robot desconectado` | El ESP32 se conectó o se desconectó |
| `🎚️ Frase del robot: 1.8 s, pico -20 dBFS` | El micrófono del robot mandó una frase, con su volumen |
| `(ignorado, no dijo "Aries"): ...` | Escuchó algo, pero no era para Aries |
| `🎙️ Oí (es): "Aries, avanza dos metros"` | Entendió la frase (`es` o `en` es el idioma) |
| `⌨️ Escribieron: "..."` | Llegó un comando escrito desde el monitor |
| `📡 Al robot: avanzar 2` | Le mandó la acción al ESP32 |
| `🔊 Aries dice: "..."` | Lo que dice por el parlante |

**Ventana 2 (el robot):**

| Línea | Qué significa |
|---|---|
| `Aries dice: "..."` | La respuesta que recibió |
| `>> MOTORES: ...` | Lo que van a hacer los motores (por ahora solo se muestra, todavía no se mueven) |
| `>> (sin movimiento)` | Respuesta sin movimiento (saludo, clima o "no entendí") |
| `Se perdió la conexión con el servidor. Freno por seguridad.` | Se cayó el cerebro o el WiFi: el robot se detiene solo y se reconecta cuando puede |
| `AVISO: el micrófono ...` | El micrófono está mal conectado (ver [INSTALACION.md](INSTALACION.md#problemas-comunes)) |

## Cambiar de micrófono

Si el micrófono del robot no funciona, usa el de la computadora. **No hace falta tocar cables ni
subir el firmware de nuevo.**

1. Ventana 1: **Ctrl+C** (si pregunta "¿Desea terminar el trabajo por lotes?", escribe **S**).
2. Abre `iniciar.bat` de nuevo y elige **2** (o escribe `.\iniciar.bat pc`).
3. Tiene que decir `🎤 Micrófono: el de la COMPUTADORA`.

Ahora le hablas a la computadora; el robot sigue recibiendo las acciones y el parlante sigue
hablando. Para elegir qué micrófono de la PC se usa (por ejemplo, un headset):
**Configuración → Sistema → Sonido → Entrada**, antes de encender el cerebro.

Para volver al del robot: Ctrl+C y `.\iniciar.bat robot`.

## Revisar el volumen del micrófono del robot

En la ventana 2 escribe `nivel` y presiona Enter. Habla normal a unos 30 cm:

| Mientras hablas marca | Qué hacer |
|---|---|
| Entre **-35 y -10 dBFS** | Está bien |
| Menos de **-40** | Muy bajo: en `robot_wifi.ino` baja `CORRIMIENTO` (12 → 11) y vuelve a subir el firmware (ver tabla de comandos) |
| `SATURA` | Muy alto: sube `CORRIMIENTO` (12 → 13) y vuelve a subir el firmware (ver tabla de comandos) |

Escribe `nivel` otra vez para ocultar la barra.

## Apagar

1. Ventana 2: **Ctrl+C** (cierra el monitor).
2. Ventana 1: **Ctrl+C** y después **S** (apaga el cerebro). El robot dice "Freno por seguridad" y se queda esperando.

## Comandos de referencia

Escríbelos en una terminal abierta en la carpeta `robot-ia` (los del firmware, en
`robot-ia\firmware\robot_wifi`). Cambia `COM3` por el puerto de tu ESP32.

| Para | Comando |
|---|---|
| Encender el cerebro (pregunta el micrófono) | `.\iniciar.bat` (o doble clic) |
| Encender con el micrófono del robot | `.\iniciar.bat robot` |
| Encender con el micrófono de la PC | `.\iniciar.bat pc` |
| Guardar lo que escucha el robot en `grabaciones` | `.\iniciar.bat robot --guardar-audio` |
| Saber en qué puerto está el ESP32 | `arduino-cli board list` |
| Ver el robot | `arduino-cli monitor -p COM3 -c baudrate=115200` |
| Compilar el firmware | `arduino-cli compile --fqbn esp32:esp32:esp32 .` |
| Subir el firmware (con el monitor cerrado) | `arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32 .` |
| Compilar el firmware sin micrófono | `arduino-cli compile --fqbn esp32:esp32:esp32 --build-property "compiler.cpp.extra_flags=-DENVIAR_AUDIO=0" .` |
| Probar la voz sin el robot (con el cerebro apagado) | `robot-env\Scripts\python.exe escucha.py` |
| Ver si Gemma está en la tarjeta gráfica | `ollama ps` |

En Ubuntu: `bash iniciar.sh` en lugar de `.\iniciar.bat`, el puerto es `/dev/ttyUSB0`, y la voz
sin robot se prueba con `robot-env/bin/python escucha.py`.

Si algo no funciona, mira la tabla de [problemas comunes](INSTALACION.md#problemas-comunes).
