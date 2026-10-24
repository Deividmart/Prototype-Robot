# Cómo armar a Aries

Guía para montar todo sobre el chasis HC-T2 (la base de acrílico negro con 2 motores amarillos y
rueda loca) y conectar cada componente al ESP32. Para instalar los programas en la PC, mira
[INSTALACION.md](INSTALACION.md); para usarlo, [USO.md](USO.md).

⚠️ **Todo se conecta con el USB desenchufado y el interruptor de las pilas apagado.**

## Qué lleva el robot

| Componente | Para qué sirve | Se alimenta de |
|---|---|---|
| Chasis HC-T2: 2 motores amarillos (TT), 2 ruedas, rueda loca, interruptor | La base que se mueve | — |
| 4 pilas AA en su portapilas (6 V) | Energía para todo: motores y, por VIN, el ESP32 y los sensores | — |
| ESP32 de 30 pines | El controlador: lee los sensores, mueve los motores, habla con la PC por WiFi | Las pilas, por su pin VIN (y el USB-C cuando se programa) |
| Driver de motores TB6612 | Le da la fuerza de las pilas a los motores según lo que pide el ESP32 | 3,3 V (lógica) y pilas (motores) |
| 2 sensores de velocidad de ranura (encoders) + los 2 discos del kit | Cuentan las vueltas de cada rueda: posición y velocidad | 3,3 V |
| MPU6050 (acelerómetro y giroscopio) | Aceleración y velocidad angular | 3,3 V |
| INA219 | Voltaje, corriente y potencia de las pilas de los motores | 3,3 V |
| Micrófono INMP441 | Escucha "Aries, ..." | Pin D27 (3,3 V) |
| 1 protoboard MB-102 | Donde van los módulos (TB6612, INA219, MPU6050) y los rieles de 3,3 V y GND | — |
| Unos 17 cables hembra-macho (y 4 hembra-hembra para el micrófono) | Conectan el ESP32 con la protoboard | — |
| Parlante Bluetooth | La voz de Aries (se conecta a la PC, no al ESP32) | Su propia batería |

El **relé ya no se usa**: el TB6612 enciende, apaga y frena los motores. Quítalo para liberar el pin D13.

## Antes de armar: decisiones de diseño

### Dónde es adelante

Decidan cuál lado del robot es **adelante** y márquenlo con un pedazo de cinta. Se recomienda
**las ruedas con motor adelante y la rueda loca atrás**: así la rueda loca va arrastrada y el
robot anda más derecho. **Izquierda y derecha** se miran siempre parado detrás del robot, mirando
hacia adelante. Todo lo demás (qué motor es el izquierdo, hacia dónde apunta el MPU6050) depende
de esta decisión: no la cambien después.

### Peso y equilibrio

- **Las pilas (unos 100 g) van cerca del eje de las ruedas con motor**, no sobre la rueda loca:
  con peso encima, las ruedas agarran mejor el piso y no patinan (si patinan, los encoders
  cuentan vueltas que el robot no anduvo).
- El peso repartido parejo entre izquierda y derecha: si un lado pesa más, el robot se desvía.
- **Para los experimentos de Newton**, dejen un espacio plano sobre el eje para poner pesas
  conocidas (monedas, tuercas pesadas en la balanza) y comparar la aceleración con distinta masa.

### Dónde va cada cosa

El chasis de un solo piso queda justo. Lo más cómodo es un **segundo piso** con 4 separadores de
bronce M3 de 30 a 40 mm y una placa de acrílico, MDF o cartón grueso:

```
          ADELANTE (ruedas con motor)
   ┌──────────────────────────────────────┐
   │  PISO DE ARRIBA                       │
   │   parlante Bluetooth                  │
   │   micrófono (lejos de los motores)    │
   ├──────────────────────────────────────┤
   │  CHASIS (arriba)                      │
   │   protoboard: TB6612, INA219, MPU6050 │
   │   ESP32 al lado, unido con cables     │
   │   interruptor                         │
   ├──────────────────────────────────────┤
   │  CHASIS (abajo)                       │
   │   motores, discos y encoders          │
   │   portapilas (cerca del eje)          │
   └──────────────────────────────────────┘
          ATRÁS (rueda loca)
```

Sin segundo piso también se puede: pilas debajo del chasis cerca del eje, protoboard y ESP32 arriba, y el
parlante sujeto con velcro donde quede espacio. Lo importante:

- **El conector USB-C del ESP32 hacia un borde**, para poder subirle el firmware sin desarmar.
- **El interruptor y el portapilas a mano**, para apagar rápido y cambiar pilas.
- **Ningún cable cerca de las ruedas**: amárrenlos con precintos (bridas) al chasis.

### El MPU6050

- **Plano, firme y con la flecha X apuntando hacia adelante.** El módulo GY-521 tiene las flechas X
  e Y dibujadas. Si queda torcido, mide parte de la gravedad como si el robot acelerara.
- **Lo más cerca posible del punto medio entre las dos ruedas.** Ese es el centro de giro: ahí la
  aceleración centrípeta medida es exactamente la del robot. Si queda lejos, al girar en el lugar
  mide además una aceleración por la distancia al centro. Anoten esa distancia.
- Pegado con cinta doble faz de espuma (amortigua la vibración de los motores) o atornillado.

### Los encoders

> **Decisión del equipo (19/10/2026): el robot va sin encoders.** `D34` y `D35` quedan libres. La
> velocidad y la posición se calculan con el MPU6050 y con el modelo del motor (voltaje y corriente
> del INA219). Lo de abajo queda solo por si algún día los ponen.

- El **disco de ranuras va en el eje del motor, del lado de adentro** (paso 2 del manual del chasis).
- El **sensor de ranura se atornilla al chasis** (hay ranuras al lado de cada motor) de modo que el
  disco pase **por el medio de la horquilla sin tocarla**. Giren la rueda con la mano: no tiene que
  rozar, y el LED del sensor tiene que parpadear con cada ranura.
- **Cuenten las ranuras del disco** (normalmente 20): hace falta para calcular la distancia.

### Ruido eléctrico de los motores

Los motores amarillos generan chispas internas que meten ruido en los sensores, el micrófono y el WiFi.

- Si tienen, suelden un **capacitor cerámico de 100 nF (104)** entre las dos patitas de cada motor.
- Si tienen, pongan un **capacitor electrolítico de 100 µF** entre VM y GND del TB6612 (la pata
  más larga, el +, a VM).
- **Cables de los motores trenzados** (enrollados entre sí) y lejos de los cables del micrófono.
- **Cables del micrófono cortos** (menos de 15 cm): sus señales son rápidas y captan ruido.

### Alimentación: todo con las 4 pilas

Las 4 pilas AA (6 V) alimentan todo el robot. Después del interruptor, el cable `+` se divide en dos
caminos:

| Camino | Va a | Para qué |
|---|---|---|
| Motores | INA219 VIN+ → INA219 VIN− → TB6612 VM | Mueve los motores. El INA219 queda solo en este camino, así mide únicamente lo que consumen los motores (lo que importa para la física). |
| Electrónica | Pin **VIN** del ESP32 | El ESP32 trae un regulador que baja los 6 V a 3,3 V y los saca por su pin **3V3**. De ahí se alimentan todos los sensores y la lógica del TB6612. |

- **Un solo GND para todo**: el `−` de las pilas, el GND del ESP32 y el de cada módulo.
- **Ningún sensor a VIN ni a 6 V**: todos al riel de **3,3 V** que sale del pin 3V3. Si un módulo
  recibe 5 o 6 V, devuelve señales de ese voltaje y el ESP32 no las aguanta.
- **Los 6 V de las pilas nunca tocan el riel de 3,3 V.**
- **Se puede conectar el USB con las pilas prendidas** para subir programas: la placa del ESP32 tiene
  un diodo que evita que el USB y las pilas se mezclen.
- Si tienen, pongan un **capacitor electrolítico de 100 µF entre VIN y GND** del ESP32 (la pata
  larga, el `+`, a VIN): amortigua la caída de voltaje cuando arrancan los motores.
- **Pilas gastadas = el ESP32 se reinicia** cada vez que arrancan los motores. El regulador necesita
  al menos unos 4,4 V; si el INA219 marca menos de 4,8 V con los motores andando, cambien las pilas.
  Usen 4 de la misma marca y con la misma carga.

**¿Y el reductor de voltaje (step-down)?** Con 4 pilas AA no conviene. Un reductor necesita recibir
al menos 1 a 1,5 V más de lo que entrega: con 6 V que bajan a 5 V al arrancar los motores, no puede
dar 5 V estables. Ajustado a 3,3 V sí funcionaría, pero habría que conectarlo al pin 3V3 sin pasar por
el regulador del ESP32: si queda mal ajustado, por ejemplo en 6 V, quema el ESP32 y todos los sensores.
Además pelearía con el regulador del ESP32 cada vez que se conecte el USB. El reductor sirve si más
adelante cambian a 2 baterías de litio 18650 (7,4 V): ajustado a **5,0 V, medido con multímetro antes
de conectarlo**, va a VIN.

## Conexiones

### El ESP32 y la protoboard

En una protoboard MB-102 el ESP32 entra a caballo, pero tapa por completo una de sus dos filas de
patas (no queda ningún hueco libre al lado). Por eso los módulos van en una protoboard y el ESP32 en
otra, o fuera. La tabla de pines de abajo no cambia.

**Opción usada: el ESP32 en una segunda protoboard.**

1. La protoboard de los módulos va a la izquierda; la segunda, a su derecha.
2. El ESP32 va con el **USB-C hacia arriba**: así la fila `3V3 … D23` queda a la izquierda. Esa
   fila se mete en la **columna J** (la última, junto a los rieles de la derecha) de la segunda
   protoboard, de la **fila 25** (`3V3`) a la **fila 11** (`D23`): 25 3V3, 24 GND, 23 D15, 22 D2,
   21 D4, 20 RX2, 19 TX2, 18 D5, 17 D18, 16 D19, 15 D21, 14 RX0, 13 TX0, 12 D22, 11 D23. La fila
   `VIN … EN` queda **al aire**, por fuera del borde. Revisen que esas patas
   no toquen los rieles ni nada metálico.
3. Cada cable de la tabla que sale de `3V3`, `GND`, `D22`, `D21`, `D19`, `D5`, `D18`, `D23`, `RX2`,
   `D4` o `TX2` sale de un hueco libre (F a I) de la fila de esa pata, con un cable **macho-macho**.
4. A las patas al aire (`VIN`, `D34`, `D35` y las del micrófono) se les pone la punta **hembra** de un
   cable: hembra-macho para `VIN` (a la fila de 6 V), hembra-hembra para los encoders y el micrófono.
   Los conectores necesitan unos 1,5 cm debajo de las patas: pongan la protoboard de modo que el
   ESP32 quede asomado por fuera del borde del chasis. Mientras el ESP32 esté en el USB, `VIN` no
   hace falta.

**Opción A, sin segunda protoboard: cables hembra-macho (unos 17).**

1. Peguen el ESP32 al chasis (o al segundo piso) **boca abajo, con las patas hacia arriba**, sobre
   cinta doble faz de espuma. Antes, tómenle una foto a las etiquetas de los pines o anoten el orden
   en un papel: boca abajo puede que no se lean.
2. Cada pata que se usa lleva un cable: la punta **hembra** en la pata del ESP32 y la punta
   **macho** en la protoboard, en la fila del módulo que le toca (o directo al riel, para 3V3 y GND).
3. El micrófono puede ir directo al ESP32 con cables **hembra-hembra** (los dos tienen patas macho).
4. Amarren el manojo de cables con un precinto cerca del ESP32 para que ninguno se suelte con la
   vibración.

**Opción B, si pueden comprar una: base de expansión para ESP32 de 30 pines.** Es una placa con un
zócalo donde se encaja el ESP32 y cada pin sale con su propio GND y 3,3 V. Revisen que sea para
**30 pines** (el de ustedes) y no para 38. Los cables van de la base a la protoboard igual que en la
opción A, pero quedan más firmes.

**En la protoboard:**

1. Usen un riel largo para **3,3 V** (cable desde el pin `3V3` del ESP32) y el de al lado para
   **GND** (cable desde `GND`). Márquenlos con cinta.
2. En algunas MB-102 los rieles están **cortados en la mitad** (la línea roja o azul tiene un hueco
   en el centro). Si la suya es así, pongan un cable puente entre las dos mitades de cada riel.
3. El TB6612 va **a caballo sobre el canal del medio** (una fila de patas a cada lado). El INA219 y
   el MPU6050, que tienen sus patas en una sola fila, van con cada pata en una fila distinta.
4. ⚠️ **Ninguna pata de un módulo en los rieles largos**: todas las patas de esa línea quedarían
   unidas entre sí (cortocircuito).
5. Los 6 V de las pilas **no van a ningún riel largo**: usan una sola fila, la fila 55, marcada con
   cinta (ver la distribución de abajo).

### Distribución en la protoboard

Se usa la protoboard blanca con letras y números **en relieve**. Pónganla con las letras **A B C D E
│ F G H I J arriba**: así la columna **A** queda a la izquierda, junto a los rieles de ese lado, y la
**fila 1 queda abajo**. Los números suben hacia las letras (20, 25 … 55, 60).

Un hueco se nombra con su fila y su columna: **10a** es la fila 10, columna A.

**Rieles:** la protoboard no tiene colores, así que márquenlos con marcador o cinta. De los dos rieles
de la izquierda, el de **afuera** es **+3,3 V** y el de **adentro** (junto a la columna A) es **GND**.
Los rieles de la derecha **no se usan** (tápenlos con cinta que diga "NO"). Como no se ve si están
cortados en la mitad, pongan en cada riel de la izquierda un cable que una un hueco de arriba con
uno de abajo del mismo riel: si era continuo, no pasa nada.

```
 +3,3 V  GND    A B C D E │ F G H I J        (las letras van ARRIBA)
                55  6 V de las pilas (lado A–E)
                44  encoder derecho (fila de paso)
                42  encoder izquierdo (fila de paso)
                35  MPU6050: VCC arriba (fila 35), patas en la columna E, cuerpo hacia la derecha
                28
                20  INA219: VCC arriba (fila 20), patas en la columna E, cuerpo hacia la derecha
                15
                10  TB6612 a caballo del canal: VM (izquierda) y PWMA (derecha) arriba
                 3
                 1  (abajo, lejos de las letras)
```

**Cómo van los módulos** (todos con las letras de cada módulo hacia arriba):

- **TB6612, filas 3 a 10, a caballo sobre el canal.** La fila de patas **PWMA … GND** a la
  **derecha** (mitad F–J) con **PWMA en la fila 10**, la de arriba; la fila **VM … GND** queda a la
  **izquierda** (mitad A–E) con **VM en la fila 10**.
- **INA219, filas 15 a 20, patas en la columna E**, con **VCC arriba, en la fila 20**, y Vin+ abajo,
  en la 15. El cuerpo del módulo queda hacia la derecha, encima del canal.
- **MPU6050, filas 28 a 35, patas en la columna E**, con **VCC arriba, en la fila 35**, e INT abajo,
  en la 28. El cuerpo hacia la derecha, encima del canal.

Así queda cada fila:

| Fila | Mitad A–E | Mitad F–J |
|---|---|---|
| 10 | TB6612 VM | TB6612 PWMA |
| 9 | TB6612 VCC | TB6612 AIN2 |
| 8 | TB6612 GND | TB6612 AIN1 |
| 7 | TB6612 A01 | TB6612 STBY |
| 6 | TB6612 A02 | TB6612 BIN1 |
| 5 | TB6612 B02 | TB6612 BIN2 |
| 4 | TB6612 B01 | TB6612 PWMB |
| 3 | TB6612 GND | TB6612 GND |
| 20 a 15 | INA219: VCC, GND, SCL, SDA, Vin−, Vin+ | — |
| 35 a 28 | MPU6050: VCC, GND, SCL, SDA, XDA, XCL, AD0, INT | — |

**Todos los cables, hueco por hueco:**

| # | Desde | Hasta | Cable |
|---|---|---|---|
| 1 | 9a (TB6612 VCC) | Riel +3,3 V | macho-macho |
| 2 | 8a (TB6612 GND) | Riel GND | macho-macho |
| 3 | 3a (TB6612 GND) | Riel GND | macho-macho |
| 4 | 20a (INA219 VCC) | Riel +3,3 V | macho-macho |
| 5 | 19a (INA219 GND) | Riel GND | macho-macho |
| 6 | 16a (INA219 Vin−) | 10a (TB6612 VM) | macho-macho |
| 7 | 55b | 15a (INA219 Vin+) | macho-macho |
| 8 | 35a (MPU6050 VCC) | Riel +3,3 V | macho-macho |
| 9 | 34a (MPU6050 GND) | Riel GND | macho-macho |
| 10 | 33b (SCL del MPU6050) | 18a (SCL del INA219) | macho-macho |
| 11 | 32b (SDA del MPU6050) | 17a (SDA del INA219) | macho-macho |
| 12 | Motor izquierdo, cable rojo | 7a (A01) | el del motor |
| 13 | Motor izquierdo, cable negro | 6a (A02) | el del motor |
| 14 | Motor derecho, cable negro | 5a (B02) | el del motor |
| 15 | Motor derecho, cable rojo | 4a (B01) | el del motor |
| 16 | Pilas `−` (negro del portapilas) | Riel GND | el del portapilas |
| 17 | Pilas `+` (el que sale del interruptor) | 55a | el del interruptor |
| 18 | ESP32 3V3 | Riel +3,3 V | hembra-macho |
| 19 | ESP32 GND | Riel GND | hembra-macho |
| 20 | ESP32 VIN | 55c | hembra-macho |
| 21 | ESP32 D19 | 10j (PWMA) | hembra-macho |
| 22 | ESP32 D5 | 9j (AIN2) | hembra-macho |
| 23 | ESP32 D18 | 8j (AIN1) | hembra-macho |
| 24 | ESP32 D23 | 7j (STBY) | hembra-macho |
| 25 | ESP32 RX2 | 6j (BIN1) | hembra-macho |
| 26 | ESP32 D4 | 5j (BIN2) | hembra-macho |
| 27 | ESP32 TX2 | 4j (PWMB) | hembra-macho |
| 28 | ESP32 D22 | 33a (SCL del MPU6050) | hembra-macho |
| 29 | ESP32 D21 | 32a (SDA del MPU6050) | hembra-macho |
| 30 | Encoder izquierdo D0 | 42a | hembra-macho |
| 31 | ESP32 D34 | 42b | hembra-macho |
| 32 | Encoder derecho D0 | 44a | hembra-macho |
| 33 | ESP32 D35 | 44b | hembra-macho |
| 34 | Encoder izquierdo VCC y GND | Riel +3,3 V y riel GND | 2 hembra-macho |
| 35 | Encoder derecho VCC y GND | Riel +3,3 V y riel GND | 2 hembra-macho |
| 36 | Micrófono SCK, WS, SD, VDD | ESP32 D32, D25, D33, D27 | 4 hembra-hembra |
| 37 | Micrófono GND y L/R | ESP32 GND (el de al lado de VIN) y D26 (el firmware lo pone en 0 V) | 2 hembra-hembra |
| 38 | Puente: riel +3,3 V, hueco de arriba | Riel +3,3 V, hueco de abajo | macho-macho |
| 39 | Puente: riel GND, hueco de arriba | Riel GND, hueco de abajo | macho-macho |

El MPU6050 y el INA219 comparten SCL y SDA, pero en cada pata del ESP32 cabe un solo cable: por eso
el ESP32 va a la fila del INA219 (cables 28 y 29) y de ahí sale otro cable a la fila del MPU6050
(cables 10 y 11).

En total: **13 macho-macho**, **22 hembra-macho** y **4 hembra-hembra**. Si faltan macho-macho,
sirven pedazos de alambre de cable UTP (el de internet) con 1 cm pelado en cada punta.

> Regla de la protoboard: dos cosas solo se conectan si están en el mismo grupito de 5
> agujeros (la misma fila y del mismo lado del canal del medio).

Colores de cable sugeridos: **rojo** = 6 V de las pilas, **naranja** = 3,3 V, **negro** = GND,
otros colores = señales.

### Pines del ESP32

> **Cambio del 21/10/2026.** La rueda izquierda fallaba a ratos: los resortes de la protoboard de los
> módulos en las filas del lado A del TB6612 hacían mal contacto. El TB6612 pasó a la **protoboard
> del ESP32, filas 53 a 60** (VM y PWMA en la 60), y AIN1 y AIN2 pasaron a **D32** (al aire) y **D15**.
> En esa protoboard: lado izquierdo 60b VM → 16a del INA219, 59b VCC → riel 3,3 V, 58b y 53b GND →
> riel GND, 57b/56b motor izquierdo rojo/negro, 55b/54b motor derecho negro/rojo; lado derecho 60h PWMA
> ← fila 16 (D19), 59h AIN2 ← fila 23 (D15), 58h AIN1 ← D32, 57h STBY ← fila 11 (D23), 56h BIN1 ← fila 20
> (RX2), 55h BIN2 ← fila 21 (D4), 54h PWMB ← fila 19 (TX2). Las tablas de filas 3 a 10 de más abajo
> quedan como historia.
>
> **Energía (21/10/2026).** Con pilas cansadas el voltaje cae de 5,5 V a ~4 V al moverse, y como el ESP32
> toma la energía de las mismas pilas (VIN), se reiniciaba al arrancar los motores ("Brownout"). El
> firmware ahora arranca los motores de a poco y no se reinicia por bajones cortos, pero lo de fondo es:
> pilas nuevas, o mejor, **alimentar el ESP32 con una batería USB (power bank) por su USB-C** y quitar
> el cable 55c → VIN, así las pilas quedan solo para los motores (los GND siguen unidos por los rieles).
>
> **Pilas de litio (22/10/2026).** Las 4 AA se cambian por un portapilas de **2 pilas 18650 en serie**
> (7,4 V; 8,4 V cargadas) que trae su propio interruptor: el interruptor del chasis se quita, el rojo del
> portapilas va a **55a** y el negro al riel **GND**. El firmware recorta la potencia para que los
> motores (de 6 V) reciban en promedio 6 V como máximo, y si las pilas bajan de 6,4 V con el robot quieto
> deja de moverse y la matriz muestra **BAT**: hay que cargarlas (fuera del robot, con su cargador).
> Si se vuelve a las 4 pilas AA, hay que poner `PILAS_DE_LITIO = false` en el firmware (si no, con 5,5 V
> se cree "litio descargado" y no se mueve).

| Pin del ESP32 | Va a | Para qué |
|---|---|---|
| **3V3** | Riel de 3,3 V | Alimenta sensores y la lógica del TB6612 |
| **GND** | Riel de GND | Tierra común |
| **VIN** | Pilas `+`, después del interruptor | Alimenta el ESP32 (su regulador da los 3,3 V del pin 3V3) |
| **D32** | Micrófono SCK | Reloj del audio |
| **D25** | Micrófono WS | Canal del audio |
| **D33** | Micrófono SD | Datos del audio |
| **D27** | Micrófono VDD | Alimentación del micrófono (el firmware lo pone en 3,3 V) |
| **D26** | Micrófono L/R | Elige el canal izquierdo (el firmware lo pone en 0 V) |
| **D21** | SDA del MPU6050 **y** del INA219 | Datos I2C (los dos comparten el cable) |
| **D22** | SCL del MPU6050 **y** del INA219 | Reloj I2C (los dos comparten el cable) |
| **D34** | D0 del encoder izquierdo | Cuenta ranuras (pin solo de entrada) |
| **D35** | D0 del encoder derecho | Cuenta ranuras (pin solo de entrada) |
| **D19** | TB6612 PWMA | Velocidad del motor izquierdo |
| **D32** | TB6612 AIN1 | Sentido del motor izquierdo (era D18) |
| **D15** | TB6612 AIN2 | Sentido del motor izquierdo (era D5) |
| **TX2** (GPIO 17) | TB6612 PWMB | Velocidad del motor derecho |
| **RX2** (GPIO 16) | TB6612 BIN1 | Sentido del motor derecho |
| **D4** | TB6612 BIN2 | Sentido del motor derecho |
| **D23** | TB6612 STBY | Enciende o apaga todo el driver |
| **D13** | Matrices DIN | Datos de la cara |
| **D14** | Matrices CLK | Reloj de la cara |
| **D27** | Matrices CS | Avisa a las matrices que les llegan datos (era el VDD del micrófono, que ya no está) |

**Libres** para más sensores: D2, D5, D18, D25, D26, D33, D34, D35, VP (36) y VN (39) (VP y VN solo de entrada).
**No usen**: TX0 y RX0 (son del cable USB) ni D12 (si está en alto al encender, el ESP32 no arranca).

### Cada módulo, pin por pin

**Micrófono INMP441** (igual que antes):

| INMP441 | Va a |
|---|---|
| VDD | D27 |
| GND | GND del ESP32 (el de al lado de VIN, en la fila al aire) |
| L/R | D26 (el firmware lo pone en 0 V) |
| WS | D25 |
| SCK | D32 |
| SD | D33 |

**MPU6050 (GY-521)**:

| MPU6050 | Va a |
|---|---|
| VCC | Riel 3,3 V |
| GND | Riel GND |
| SCL | D22 |
| SDA | D21 |
| XDA, XCL, AD0, INT | Nada |

**INA219**:

| INA219 | Va a |
|---|---|
| VCC | Riel 3,3 V |
| GND | Riel GND |
| SCL | D22 (junto con el del MPU6050) |
| SDA | D21 (junto con el del MPU6050) |
| VIN+ | Interruptor (lo que viene del `+` de las pilas) |
| VIN− | VM del TB6612 |

**Encoders** (los dos iguales):

| Sensor de ranura | Izquierdo | Derecho |
|---|---|---|
| VCC | Riel 3,3 V | Riel 3,3 V |
| GND | Riel GND | Riel GND |
| D0 | D34 | D35 |
| A0 (si tiene) | Nada | Nada |

**Cara: 4 matrices 8x8 con MAX7219** (módulo 4 en 1, tipo FC16, LEDs 1088AS). Se conecta por
la punta que dice DIN (la otra punta dice DOUT y queda libre):

| Matrices | Va a |
|---|---|
| VCC | Riel 3,3 V |
| GND | Riel GND |
| DIN | D13 |
| CS | D27 |
| CLK | D14 |

Van a 3,3 V con brillo bajo (`BRILLO = 1` en el firmware): a más brillo consumen más y el ESP32
se puede reiniciar. Qué muestran: ojos cerrados sin conexión con la PC, ojos que parpadean y miran
a los lados cuando espera, ojos contentos (^ ^) al contestar, la velocidad en m/s al avanzar o
retroceder y los grados al girar.

**Driver TB6612** (motor A = rueda izquierda, motor B = rueda derecha):

| TB6612 | Va a |
|---|---|
| VM | VIN− del INA219 (6 V de las pilas, ya medidos) |
| VCC | Riel 3,3 V |
| GND (todos los que tenga) | Riel GND |
| PWMA / AIN1 / AIN2 | D19 / D18 / D5 |
| PWMB / BIN1 / BIN2 | TX2 / RX2 / D4 |
| STBY | D23 |
| AO1 y AO2 | Los 2 cables del motor izquierdo |
| BO1 y BO2 | Los 2 cables del motor derecho |

El orden de los dos cables de cada motor no importa ahora: si una rueda gira al revés, se
invierten en el TB6612 (lo dice la prueba de motores).

### El camino de la corriente de las pilas

```
Pilas (+) ──► interruptor ──┬──► INA219 VIN+ ──► INA219 VIN− ──► TB6612 VM ──► motores
                            │
                            └──► VIN del ESP32 ──► (regulador interno) ──► pin 3V3 ──► riel 3,3 V ──► sensores
Pilas (−) ──────────────────────────────────────────────────────────────► riel GND (y GND del ESP32)
```

El interruptor ya tiene sus cables rojo y negro. El rojo (`+`) de las pilas pasa por el interruptor; el
negro (`−`) va directo al riel de GND. El camino hacia VIN sale **antes** del INA219, para que el
INA219 mida solo los motores.

Al prender el interruptor arrancan a la vez el ESP32 y los motores. Eso no es un problema: el pin STBY
del TB6612 queda apagado hasta que el firmware lo enciende, así que las ruedas no se mueven solas mientras
el ESP32 arranca.

## Orden para armar y probar

Cada paso se prueba antes de seguir: si algo falla, se sabe que es lo último que se conectó.

1. **Mecánica.** Motores firmes, discos de ranuras en el eje (lado de adentro), sensores de ranura
   atornillados sin rozar, rueda loca, portapilas cerca del eje, interruptor. Giren las ruedas con
   la mano: nada roza.
2. **Protoboard y ESP32.** Peguen la protoboard al chasis (trae adhesivo atrás) y el ESP32 al lado,
   boca abajo, con el USB-C hacia un borde. Quiten el relé.
3. **Rieles y micrófono.** Riel de 3,3 V, riel de GND y los 6 cables del micrófono.
4. **Sensores** (MPU6050, INA219 y encoders). Suban `test_sensores` (está en
   `robot-ia\firmware\test_sensores`; los comandos están en la sección siguiente). Debe encontrar
   los dos módulos. Empujen el robot hacia adelante y anoten qué eje cambia; gírenlo a la derecha
   y anoten el signo del giro Z.
5. **Motores.** TB6612, motores, y las pilas pasando por el interruptor y el INA219. **Levanten el
   robot** (que las ruedas giren en el aire), prendan el interruptor y suban `test_motores`. Cada
   rueda tiene que girar adelante y atrás, y cada encoder contar su propia rueda.
6. **Medidas para `robot-ia\fisica.py`**: diámetro de la rueda con caucho (6,1 cm), número de
   ranuras del disco, distancia entre el centro de las dos ruedas (de la mitad de un caucho a la
   mitad del otro) y peso del robot completo con pilas (balanza de cocina).
7. **Firmware final** (`robot_wifi`, con motores, sensores y mediciones para las gráficas).
8. **Arriba**: parlante, ordenar cables con precintos.

### Subir un programa de prueba

En una terminal abierta en la carpeta de la prueba (por ejemplo `robot-ia\firmware\test_sensores`).
Cambia `COM4` por el puerto de tu ESP32 (`arduino-cli board list`):

```
arduino-cli compile --fqbn esp32:esp32:esp32 .
arduino-cli upload -p COM4 --fqbn esp32:esp32:esp32 .
arduino-cli monitor -p COM4 -c baudrate=115200
```

El ESP32 guarda **un solo programa a la vez**: mientras tenga cargada una prueba, Aries no escucha
ni habla. Para volver, suban `robot_wifi` (paso 5 de [INSTALACION.md](INSTALACION.md)).

## Problemas comunes

| Problema | Solución |
|---|---|
| `test_sensores` no encuentra nada | SDA → D21, SCL → D22, VCC → 3,3 V y GND de los dos módulos. |
| Encuentra solo uno de los dos | El que falta tiene un cable suelto; los dos comparten SDA y SCL. |
| El voltaje de las pilas marca 0 | Interruptor apagado, o VIN+ y VIN− del INA219 sin conectar. |
| Una rueda gira al revés | Inviertan los 2 cables de ese motor en el TB6612. |
| Gira la rueda que no era | Intercambien los motores: los cables de AO1/AO2 con los de BO1/BO2. |
| Un encoder no cuenta | D0 → D34 o D35, VCC a 3,3 V, y que el disco pase por la horquilla. El LED del sensor tiene que parpadear al girar la rueda a mano. |
| Cuenta el encoder de la otra rueda | Los cables D0 están cruzados. |
| El ESP32 se reinicia cuando arrancan los motores | Pilas gastadas (cámbienlas) o falta el capacitor de 100 µF en VIN o en VM. Revisen también que el `+` y el `−` de VIN estén firmes. |
| Con el interruptor apagado, los motores giran al conectar el USB | El USB llega a los motores por la pata `VIN` del ESP32. Mientras el USB esté conectado, quiten el cable de `VIN` (el ESP32 se alimenta del USB y los motores solo de las pilas). Pónganlo de nuevo cuando el robot ande sin USB. |
| `D5` se lee siempre en alto en las pruebas | Algunos ESP32 traen una resistencia que sube `D5`. No hace daño: si la rueda izquierda gira hacia los dos lados, `D5` funciona. |
| Los motores no se mueven | STBY → D23, VM recibe las pilas (interruptor prendido), GND común. |
| El robot se desvía al avanzar | Normal: dos motores nunca son iguales. El firmware lo corrige con el giroscopio. Revisen también que ninguna rueda roce. |
| Algo funciona en la mesa y falla cuando el robot anda | Un cable hembra se aflojó en una pata del ESP32 con la vibración. Revísenlos y amárrenlos con un precinto. |
| El micrófono capta mucho ruido con los motores | Capacitores en los motores, cables del micrófono cortos y lejos de los de los motores. |
