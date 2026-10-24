"""
Resuelve las cuentas que le piden a Aries con SymPy, sin internet: operaciones, ecuaciones,
derivadas, integrales y conversiones de unidades.

Gemma solo traduce lo que dijeron a una expresión ("sqrt(2*9.81*1.5)", "x**2 - 4 = 0",
"5*kilowatt*hour to joule"); la cuenta la hace SymPy, porque un modelo de 4B se equivoca con
los números. La frase que devuelve está pensada para decirla en voz alta (Piper).
"""
import re

import sympy as sp
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations
from sympy.physics import units as u

x, y, z, t = sp.symbols("x y z t")

# Lo que puede aparecer en una expresión. Cualquier otro nombre se rechaza: así el texto que
# llega del reconocimiento de voz no puede ejecutar nada raro.
FUNCIONES = {
    "sqrt": sp.sqrt, "cbrt": sp.cbrt, "root": sp.root, "exp": sp.exp, "log": sp.log, "ln": sp.log,
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "Abs": sp.Abs, "abs": sp.Abs, "factorial": sp.factorial, "diff": sp.diff, "integrate": sp.integrate,
    "limit": sp.limit, "simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor,
    "pi": sp.pi, "E": sp.E, "oo": sp.oo, "deg": sp.pi / 180,
    "x": x, "y": y, "z": z, "t": t,
}
UNIDADES = {
    "meter": u.meter, "kilometer": u.kilometer, "centimeter": u.centimeter, "millimeter": u.millimeter,
    "micrometer": u.micrometer, "nanometer": u.nanometer, "inch": u.inch, "foot": u.foot, "mile": u.mile,
    "second": u.second, "minute": u.minute, "hour": u.hour, "day": u.day, "year": u.year,
    "gram": u.gram, "kilogram": u.kilogram, "pound": u.pound,
    "newton": u.newton, "joule": u.joule, "watt": u.watt, "volt": u.volt, "ampere": u.ampere,
    "ohm": u.ohm, "coulomb": u.coulomb, "tesla": u.tesla, "hertz": u.hertz, "farad": u.farad,
    "henry": u.henry, "weber": u.weber, "pascal": u.pascal, "electronvolt": u.electronvolt,
    "liter": u.liter, "milliliter": u.milliliter, "kelvin": u.kelvin, "atmosphere": u.atmosphere,
    "bar": u.bar, "psi": u.psi, "radian": u.radian, "degree": u.degree,
    # Las que SymPy no trae con nombre
    "kilojoule": 1000 * u.joule, "megajoule": 10**6 * u.joule, "kilowatt": 1000 * u.watt,
    "megawatt": 10**6 * u.watt, "gigawatt": 10**9 * u.watt, "milliwatt": u.watt / 1000,
    "milliampere": u.ampere / 1000, "microampere": u.ampere / 10**6, "millivolt": u.volt / 1000,
    "kilovolt": 1000 * u.volt, "kilohm": 1000 * u.ohm, "megohm": 10**6 * u.ohm,
    "kilowatthour": 1000 * u.watt * u.hour, "calorie": sp.Rational(4184, 1000) * u.joule,
    "kilocalorie": 4184 * u.joule, "horsepower": sp.Rational(7457, 10) * u.watt, "gauss": u.tesla / 10**4,
    "milligram": u.gram / 1000, "millisecond": u.second / 1000, "microsecond": u.second / 10**6,
}
NOMBRES = {**FUNCIONES, **UNIDADES}

# Cómo se dicen las unidades (en plural, que es lo más común en un resultado)
UNIDADES_HABLADAS = {
    "meter": ("metros", "meters"), "kilometer": ("kilómetros", "kilometers"), "centimeter": ("centímetros", "centimeters"),
    "millimeter": ("milímetros", "millimeters"), "micrometer": ("micrómetros", "micrometers"),
    "nanometer": ("nanómetros", "nanometers"), "inch": ("pulgadas", "inches"), "foot": ("pies", "feet"),
    "mile": ("millas", "miles"), "second": ("segundos", "seconds"), "minute": ("minutos", "minutes"),
    "hour": ("horas", "hours"), "day": ("días", "days"), "year": ("años", "years"), "gram": ("gramos", "grams"),
    "kilogram": ("kilogramos", "kilograms"), "pound": ("libras", "pounds"), "newton": ("newtons", "newtons"),
    "joule": ("julios", "joules"), "watt": ("vatios", "watts"), "volt": ("voltios", "volts"),
    "ampere": ("amperios", "amperes"), "ohm": ("ohmios", "ohms"), "coulomb": ("culombios", "coulombs"),
    "tesla": ("teslas", "teslas"), "hertz": ("hercios", "hertz"), "farad": ("faradios", "farads"),
    "henry": ("henrios", "henries"), "weber": ("webers", "webers"), "pascal": ("pascales", "pascals"),
    "electronvolt": ("electronvoltios", "electronvolts"), "liter": ("litros", "liters"),
    "milliliter": ("mililitros", "milliliters"), "kelvin": ("kelvin", "kelvin"),
    "atmosphere": ("atmósferas", "atmospheres"), "bar": ("bares", "bars"), "psi": ("psi", "psi"),
    "radian": ("radianes", "radians"), "degree": ("grados", "degrees"), "kilojoule": ("kilojulios", "kilojoules"),
    "megajoule": ("megajulios", "megajoules"), "kilowatt": ("kilovatios", "kilowatts"),
    "megawatt": ("megavatios", "megawatts"), "gigawatt": ("gigavatios", "gigawatts"),
    "milliwatt": ("milivatios", "milliwatts"), "milliampere": ("miliamperios", "milliamperes"),
    "microampere": ("microamperios", "microamperes"), "millivolt": ("milivoltios", "millivolts"),
    "kilovolt": ("kilovoltios", "kilovolts"), "kilohm": ("kiloohmios", "kilohms"), "megohm": ("megaohmios", "megohms"),
    "kilowatthour": ("kilovatios hora", "kilowatt hours"), "calorie": ("calorías", "calories"),
    "kilocalorie": ("kilocalorías", "kilocalories"), "horsepower": ("caballos de fuerza", "horsepower"),
    "gauss": ("gauss", "gauss"), "milligram": ("miligramos", "milligrams"),
    "millisecond": ("milisegundos", "milliseconds"), "microsecond": ("microsegundos", "microseconds"),
}

_TRANSFORMACIONES = standard_transformations + (convert_xor,)
_SI = [u.meter, u.kilogram, u.second, u.ampere, u.kelvin]


class NoEntendi(ValueError):
    """La expresión no se puede leer o usa algo que no está permitido."""


def _leer(texto: str):
    texto = texto.strip()
    if not texto or "__" in texto or not re.fullmatch(r"[\w\s+\-*/^().,=]*", texto):
        raise NoEntendi(texto)
    for nombre in re.findall(r"[A-Za-z_]\w*", texto):
        if nombre not in NOMBRES:
            raise NoEntendi(nombre)
    try:
        return parse_expr(texto, local_dict=dict(NOMBRES), transformations=_TRANSFORMACIONES)
    except Exception as e:
        raise NoEntendi(texto) from e


def _numero(valor, idioma: str) -> str:
    """Un número como se dice: 4 cifras significativas, coma decimal en español, sin notación científica rara."""
    v = float(valor)
    if v != 0 and (abs(v) >= 1e12 or abs(v) < 1e-4):
        mant, exp = f"{v:.3e}".split("e")
        mant = mant.rstrip("0").rstrip(".")
        if idioma == "en":
            return f"{mant} times ten to the {int(exp)}"
        return f"{mant.replace('.', ',')} por diez a la {int(exp)}"
    if float(v).is_integer():
        texto = str(int(v))
    else:
        texto = f"{v:.4g}" if abs(v) < 1e4 else f"{v:.0f}"
    if idioma != "en":
        texto = texto.replace(".", ",")
    if texto.startswith("-"):
        texto = ("minus " if idioma == "en" else "menos ") + texto[1:]
    return texto


def _decir(expr, idioma: str) -> str:
    """Pasa una expresión simbólica a palabras ('x*cos(x) + sin(x)' -> 'x por coseno de x más seno de x')."""
    if expr.is_number and expr.is_real:
        return _numero(sp.N(expr), idioma)
    en = idioma == "en"
    texto = sp.sstr(expr)
    texto = re.sub(r"\d+\.\d+", lambda m: _numero(float(m.group()), idioma), texto)
    reemplazos = [
        ("**2", " squared" if en else " al cuadrado"), ("**3", " cubed" if en else " al cubo"),
        ("**", " to the power of " if en else " a la "), ("sqrt(", "the square root of (" if en else "raíz de ("),
        ("sin(", "sine of (" if en else "seno de ("), ("cos(", "cosine of (" if en else "coseno de ("),
        ("tan(", "tangent of (" if en else "tangente de ("), ("log(", "the logarithm of (" if en else "logaritmo de ("),
        ("exp(", "e to the (" if en else "e a la ("), ("*", " times " if en else " por "),
        ("/", " over " if en else " entre "), (" + ", " plus " if en else " más "),
        (" - ", " minus " if en else " menos "), ("-", "minus " if en else "menos "),
    ]
    for a, b in reemplazos:
        texto = texto.replace(a, b)
    return re.sub(r"\s+", " ", texto.replace("(", " ").replace(")", " ")).strip()


def _convertir(izquierda: str, derecha: str, idioma: str) -> str:
    valor, destino = _leer(izquierda), _leer(derecha)
    cociente = sp.simplify(u.convert_to(valor, _SI) / u.convert_to(destino, _SI))
    if not cociente.is_number:
        raise NoEntendi(f"{izquierda} -> {derecha}")
    # "meter/second" -> "metros por segundo": lo que va después de la barra se dice en singular
    numerador, _, denominador = derecha.partition("/")
    i = 1 if idioma == "en" else 0

    def hablar(parte: str, singular: bool) -> str:
        nombres = [UNIDADES_HABLADAS.get(c, (c, c))[i] for c in re.findall(r"[A-Za-z_]\w*", parte)]
        if singular:
            nombres = [n[:-1] if n.endswith("s") else n for n in nombres]
        return " ".join(nombres)

    nombre = hablar(numerador, False)
    if denominador:
        nombre += (" per " if idioma == "en" else " por ") + hablar(denominador, True)
    return f"{_numero(sp.N(cociente), idioma)} {nombre}"


def _resolver_ecuacion(izquierda: str, derecha: str, idioma: str) -> list[str]:
    """Las soluciones reales dichas en palabras ("x igual a 2"); lista vacía si no hay."""
    ecuacion = sp.Eq(_leer(izquierda), _leer(derecha))
    libres = sorted(ecuacion.free_symbols, key=lambda s: s.name)
    if not libres:
        raise NoEntendi("ecuación sin incógnita")
    incognita = x if x in libres else libres[0]
    soluciones = [s for s in sp.solve(ecuacion, incognita) if s.is_real is not False]
    return [f"{incognita} {'equals' if idioma == 'en' else 'igual a'} {_decir(s, idioma)}" for s in soluciones]


def _comparar(izquierda: str, derecha: str, idioma: str) -> tuple[str, str]:
    """'¿la raíz de 144 es igual a la raíz de 14?': dos lados sin incógnita -> ("si"/"no", los dos valores)."""
    a, b = _leer(izquierda), _leer(derecha)
    iguales = sp.simplify(a - b) == 0
    return ("comparacion_si" if iguales else "comparacion_no"), f"{_decir(a, idioma)}|{_decir(b, idioma)}"


def _lista(partes: list[str], idioma: str) -> str:
    if len(partes) == 1:
        return partes[0]
    return (", " if len(partes) > 2 else " ").join(partes[:-1]) + (" and " if idioma == "en" else " y ") + partes[-1]


def calcular(expresion: str, idioma: str = "es") -> tuple[str, str] | None:
    """
    Hace la cuenta y devuelve (tipo, resultado dicho en palabras), o None si no se pudo:
      ("valor", "100"), ("conversion", "18000000 julios"), ("ecuacion", "x igual a menos 2 y x igual a 2"),
      ("sin_solucion", "")
    """
    texto = (expresion or "").replace("×", "*").replace("÷", "/").replace("−", "-")
    try:
        if " to " in texto:
            izquierda, derecha = texto.split(" to ", 1)
            return "conversion", _convertir(izquierda, derecha, idioma)
        if "==" in texto:
            return _comparar(*texto.split("==", 1), idioma)
        if texto.count("=") == 1:
            izquierda, derecha = texto.split("=")
            if not (_leer(izquierda) - _leer(derecha)).free_symbols:  # sin incógnita: es una comparación
                return _comparar(izquierda, derecha, idioma)
            soluciones = _resolver_ecuacion(izquierda, derecha, idioma)
            return ("ecuacion", _lista(soluciones, idioma)) if soluciones else ("sin_solucion", "")
        resultado = _leer(texto)
        # Un número se simplifica; una expresión se desarrolla, que dicha en voz alta se entiende mejor
        resultado = sp.simplify(resultado) if resultado.is_number else sp.expand(resultado)
        frase = _decir(resultado, idioma)
        if "integrate" in texto and not resultado.is_number:
            frase += " plus a constant" if idioma == "en" else " más una constante"
        return "valor", frase
    except (NoEntendi, TypeError, ValueError, NotImplementedError, ZeroDivisionError, AttributeError):
        return None


def frase_resultado(calculo: tuple[str, str] | None, idioma: str = "es", unidad: str = "", planteo: str = "") -> str:
    """La frase completa para decir, con la unidad y la ley usada si se conocen."""
    en = idioma == "en"
    if calculo is None:
        return ("I couldn't work that out. Could you say it another way?" if en
                else "No pude resolver esa cuenta. ¿Me la dices de otra forma?")
    tipo, resultado = calculo
    previo = (planteo[:1].upper() + planteo[1:]).rstrip(".") + ". " if planteo else ""
    if tipo == "sin_solucion":
        return previo + ("That equation has no real solutions." if en else "Esa ecuación no tiene soluciones reales.")
    if tipo == "ecuacion":
        varias = " and " in resultado or " y " in resultado
        if en:
            return previo + f"The solution{'s are' if varias else ' is'} {resultado}."
        return previo + f"La{'s soluciones son' if varias else ' solución es'} {resultado}."
    if tipo.startswith("comparacion"):
        a, b = resultado.split("|")
        if tipo == "comparacion_si":
            return previo + (f"Yes, both are equal: {a}." if en else f"Sí, son iguales: los dos dan {a}.")
        return previo + (f"No, they are not equal: one is {a} and the other is {b}." if en
                         else f"No, no son iguales: uno da {a} y el otro {b}.")
    if tipo == "conversion":
        return previo + (f"That's {resultado}." if en else f"Son {resultado}.")
    con_unidad = f"{resultado} {unidad}".strip()
    return previo + (f"The result is {con_unidad}." if en else f"El resultado es {con_unidad}.")


def resolver(expresion: str, idioma: str = "es") -> str:
    """Frase lista para decir con el resultado de la expresión, o una disculpa si no se pudo."""
    return frase_resultado(calcular(expresion, idioma), idioma)


if __name__ == "__main__":
    for e in ["25*4", "sqrt(2*9.81*1.5)", "x**2 - 4 = 0", "diff(x**2*sin(x), x)", "integrate(x**2, x)",
              "5*kilowatt*hour to joule", "36*kilometer/hour to meter/second", "sin(30*deg)",
              "0.5*0.4*0.43**2", "__import__('os')", "2 = 3"]:
        print(f"{e:<35} -> {resolver(e)}  |  {resolver(e, 'en')}")
