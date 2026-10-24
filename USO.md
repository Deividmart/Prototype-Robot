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
carpeta, escribe `.\iniciar.bat`). Se abren dos cosas:

- **La ventana de las gráficas en vivo** (se cierra con la X; para reabrirla, `graficas.bat`).
- **Esta terminal**, que muestra solo lo que Aries oye, dice y le manda al robot.

Desde el 20/10/2026 el robot no tiene micrófono: se le habla por el de la **computadora** (si algún día se
lo vuelven a poner: `.\iniciar.bat robot`). Espera a ver estas líneas, unos 15 segundos:

```
Gemma cargada en la GPU
🎧 Escuchando por el micrófono de la computadora. Di "Hola Aries".
🤖 Robot conectado
```

**No cierres esta terminal**: es el cerebro del robot. Para apagar a Aries, ciérrala.

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

Funciona como Siri: el nombre lo despierta y después se le habla normal.

- **Despertarlo:** "Aries" (o "oye Aries") → contesta "¿Sí? Dime." y te escucha.
- **Conversar:** mientras sigan hablando no hace falta repetir el nombre: cada respuesta le da **15
  segundos** más de atención ("avanza dos metros"… "¿cuánto es 12 por 12?"… "cuéntame un chiste").
- **Terminar:** "gracias", "eso es todo" o "adiós" → se despide y vuelve a esperar su nombre.
- **Callarlo:** mientras habla, "para", "Aries, para", "cállate" o "stop" → deja de hablar y frena los
  motores (con el micrófono de la computadora).
- **Todo junto** también vale: "Aries, avanza dos metros".

Mientras Aries habla no escucha: espera a que termine. Si pasan 15 segundos sin hablarle, o le dijeron
"gracias", lo que se diga sin "Aries" se ignora a propósito (así no reacciona a las conversaciones de
alrededor). La ventana del cerebro muestra `👂 Te escucho 15 s` mientras está atento y `💤 Fin de la
conversación` cuando se duerme.

### Lo que entiende

Entiende **español e inglés** y contesta en el idioma en que le hablaste.

| Para... | Puedes decir | El robot hace |
|---|---|---|
| Saludar | "Hola Aries", "buenos días", "Hi Aries", "¿cómo estás?" | Se presenta y ofrece ayuda |
| Avanzar | "avanza dos metros", "move forward one meter" | `>> MOTORES: avanzar 2.0 m` |
| Retroceder | "retrocede un metro", "go back two meters" | `>> MOTORES: retroceder 1.0 m` |
| Girar | "gira a la derecha 45 grados", "turn left", "date media vuelta" | `>> MOTORES: girar 45 grados (derecha)` |
| Frenar | "para", "detente", "quieto", "stop" | `>> MOTORES: detener` (y termina el registro de las gráficas) |
| Borrar las gráficas | "reinicia", "borra las gráficas", "empieza de nuevo", "reset" | Deja las gráficas en blanco y empieza de cero |
| El clima | "¿qué clima hace?", "¿va a llover?", "how's the weather?" | Dice el clima real de Barranquilla (necesita internet) |
| Cuentas | "¿cuánto es 25 por 4?", "raíz cuadrada de 2 por 9,8 por 1,5", "seno de 30 grados", "what's 15 percent of 200?" | Hace la cuenta con SymPy (sin internet) y dice el resultado |
| Problemas de física | "si un carro va a 20 metros por segundo durante 5 segundos, ¿cuánto recorre?", "¿qué corriente pasa por 10 ohmios con 5 voltios?" | Groq plantea la fórmula, SymPy la calcula y Aries dice la ley y el resultado con su unidad |
| Explicar lo que midió | "explícame el último movimiento", "explain your last move" | Toma los números del último registro y Groq explica la física (movimiento, energía, potencia, eficiencia) |
| Charla | "cuéntame un chiste de física", "¿por qué el cielo es azul?", "y ¿por qué al atardecer es rojo?" | Responde Groq en 1 o 2 frases y recuerda lo último que hablaron (2 minutos) |
| Ecuaciones, derivadas, integrales | "resuelve x al cuadrado menos 4 igual a cero", "deriva x al cuadrado por seno de x", "integral of x squared" | Lo resuelve con SymPy y lo dice en palabras |
| Conversión de unidades | "¿cuántos julios son 5 kilovatios hora?", "convert 36 km per hour to meters per second" | Convierte con SymPy (julios, vatios, amperios, ohmios, km/h, calorías…) |
| Preguntas de conocimiento | "¿qué es la ley de Ohm?", "¿quién fue Faraday?", "¿cuántos habitantes tiene Barranquilla?", "who was Nikola Tesla?" | Responde Groq; sin internet, lee lo que tenga guardado de Wikipedia |

**Groq (inteligencia en la nube).** Las cuentas difíciles, las preguntas, la charla y las explicaciones
usan Groq, que necesita internet y una clave gratis en `robot-ia/.env` (`GROQ_API_KEY=...`, se crea
en console.groq.com; el archivo no se sube a git). Los números nunca los inventa: las cuentas las hace
SymPy y las mediciones salen de los registros. Si no hay internet, Aries se sigue moviendo y haciendo
cuentas con lo local (Gemma y SymPy); solo la charla responde "no entendí".

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

## Gráficas de los movimientos

El cerebro guarda lo que miden los sensores del robot en la carpeta `robot-ia\datos`, un archivo
`.csv` por registro (se abre con Excel):

- **Empieza** con el primer movimiento (avanzar, retroceder o girar), o cuando las ruedas giran
  solas porque alguien empujó al robot.
- **Sigue registrando sin parar**, con todos los movimientos que le pidan, hasta que digas
  **"Aries, para"**. Ahí espera a que el robot quede quieto y guarda el archivo.
- **"Aries, reinicia"** (o "borra las gráficas", "empieza de nuevo") descarta el registro en curso y
  deja las gráficas en blanco. El próximo movimiento empieza un registro nuevo desde cero. Los
  registros ya guardados con "para" no se borran.

En la ventana 1 aparece `📈 Registrando`, `🧹 Gráficas reiniciadas` y `💾 Registro guardado` con el
desplazamiento, la distancia recorrida, el ángulo, el tiempo en movimiento y la energía.

Para verlo en gráficas, haz **doble clic en `graficas.bat`** (en la carpeta `robot-ia`). Se abre una
ventana que se actualiza sola con lo que se está registrando:

- **Menú "Elige la gráfica"**: una magnitud sola en grande (con su pico o valor final marcado) o
  todas juntas: posición, velocidad, aceleración, velocidad angular, ángulo, aceleración
  centrípeta, voltaje, corriente, potencia, energía y distancia recorrida. En velocidad,
  aceleración y ángulo se comparan dos cálculos: el del sensor (MPU6050) y el del modelo del motor
  (voltaje y corriente del INA219).
- **Líneas punteadas**: cada comando ("avanza 2 m", "gira 90° der.", "para") en el momento en que se dio.
- **◀ Anterior / Siguiente ▶**: recorren los registros guardados. **● En vivo** vuelve al actual.
- **Barra de abajo**: la lupa acerca una zona, la casa vuelve a la vista normal y el disquete guarda la imagen.

El robot no tiene encoders: la velocidad sale del acelerómetro corregido con el modelo del motor
(V = I·R + K·ω), y la posición de integrar esa velocidad. Los cálculos usan las medidas del robot
que están al principio de `fisica.py` (diámetro de la rueda, ancho entre ruedas, masa y los datos
del motor). **Mídanlas y cámbienlas ahí** para que los resultados den bien. Para calibrar la
distancia: pidan "avanza un metro", midan con una cinta cuánto anduvo y pongan distancia real / 1 m
en `AJUSTE_DISTANCIA`, en `fisica.py` y en `robot_wifi.ino`.

### Probar sin el robot armado

`simular_robot.py` hace de ESP32 con un modelo físico del robot (motores amarillos, pilas AA,
rozamiento). Con el cerebro encendido (ventana 1), abre otra terminal en `robot-ia` y escribe:

```
robot-env\Scripts\python.exe simular_robot.py
```

Escríbele comandos como en el monitor del ESP32 (`avanza dos metros`, `gira a la derecha`, `para`,
`reinicia`) o `empujar` para darle un empujón con la mano. Con `graficas.bat` abierto vas viendo
cómo se dibuja todo.

## Apagar

1. Ventana 2: **Ctrl+C** (cierra el monitor).
2. Ventana 1: **Ctrl+C** y después **S** (apaga el cerebro). El robot dice "Freno por seguridad" y se queda esperando.

## Comandos de referencia

Escríbelos en una terminal abierta en la carpeta `robot-ia` (los del firmware, en
`robot-ia\firmware\robot_wifi`). Cambia `COM3` por el puerto de tu ESP32.

| Para | Comando |
|---|---|
| Encender el cerebro y las gráficas (micrófono de la PC) | `.\iniciar.bat` (o doble clic) |
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
| Gráficas en vivo | `.\graficas.bat` (o doble clic) |
| Abrir el último movimiento (y guardarlo como imagen `.png`) | `.\graficas.bat --ultimo` |
| Abrir un movimiento guardado | `.\graficas.bat datos\<archivo>.csv` |
| Lista de movimientos con sus resultados | `.\graficas.bat --lista` |
| Probar con un robot simulado (con el cerebro encendido) | `robot-env\Scripts\python.exe simular_robot.py` |

En Ubuntu: `bash iniciar.sh` en lugar de `.\iniciar.bat`, el puerto es `/dev/ttyUSB0`, y la voz
sin robot se prueba con `robot-env/bin/python escucha.py`.

Si algo no funciona, mira la tabla de [problemas comunes](INSTALACION.md#problemas-comunes).
