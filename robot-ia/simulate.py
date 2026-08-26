"""
Simulador del robot sin hardware: en vez de mandarle el JSON de acción
a un ESP32, lo imprime en consola. Sirve para validar toda la lógica
de decisión (brain.py) mientras no tenés el microcontrolador.

Uso:
    python simulate.py
    (escribí comandos como si le hablaras al robot; "salir" para terminar)
"""
from brain import preguntar


def ejecutar_accion_simulada(accion: dict) -> None:
    """Reemplaza el envío del JSON al ESP32: solo lo muestra en pantalla."""
    tipo = accion["accion"]
    parametro = accion["parametro"]

    if tipo == "avanzar":
        print(f"🤖 [SIMULADO] Avanzando {parametro} metros...")
    elif tipo == "retroceder":
        print(f"🤖 [SIMULADO] Retrocediendo {parametro} metros...")
    elif tipo == "girar":
        direccion = "derecha" if parametro >= 0 else "izquierda"
        print(f"🤖 [SIMULADO] Girando {abs(parametro)}° a la {direccion}...")
    elif tipo == "detener":
        print("🤖 [SIMULADO] Deteniéndose.")

    print(f"🔊 [TTS simulado] \"{accion['respuesta_hablada']}\"")


def main():
    print("=== Simulador de robot IA (sin ESP32) ===")
    print("Escribí un comando de voz simulado. 'salir' para terminar.\n")

    while True:
        try:
            comando = input("Vos decís: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not comando:
            continue
        if comando.lower() in {"salir", "exit", "quit"}:
            break

        try:
            accion = preguntar(comando)
        except Exception as e:
            print(f"⚠️  Error consultando a Gemma: {e}\n")
            continue

        ejecutar_accion_simulada(accion)
        print()


if __name__ == "__main__":
    main()
