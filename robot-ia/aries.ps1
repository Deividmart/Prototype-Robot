# Menú de Aries para cualquier computadora: instala lo que falte, conecta el robot a la WiFi de esta
# computadora (por USB, sin volver a cargar el firmware), carga el firmware y enciende o apaga a Aries.
# No lo corras directo: doble clic en Aries.bat
Set-Location $PSScriptRoot
$Host.UI.RawUI.WindowTitle = "Aries"
$py = Join-Path $PSScriptRoot "robot-env\Scripts\python.exe"
$archivoClave = Join-Path $PSScriptRoot ".env"

function Titulo($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }
function Pausa { Read-Host "`nPresiona Enter para volver al menú" | Out-Null }

# --- Cómo está todo ---
function Esta-Instalado {
    # La carpeta copiada de otra computadora trae robot-env, pero ese Python no funciona acá
    if (-not (Test-Path $py)) { return $false }
    & $py -c "import flask, numpy, piper" 2>$null
    return $LASTEXITCODE -eq 0
}
function Cerebro-Encendido {
    [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "server\.py" })
}
function Hay-Internet {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { return $tcp.ConnectAsync("api.groq.com", 443).Wait(3000) } catch { return $false } finally { $tcp.Dispose() }
}
function Hay-ClaveGroq {
    (Test-Path $archivoClave) -and [bool](Select-String -Path $archivoClave -Pattern '^\s*GROQ_API_KEY\s*=\s*\S' -Quiet)
}
function Wifi-PC {
    $datos = @{}
    foreach ($linea in (netsh wlan show interfaces 2>$null)) {
        if ($linea -match '^\s*SSID\s*:\s*(.+)$') { $datos.Ssid = $Matches[1].Trim() }
        elseif ($linea -match '^\s*(Perfil|Profile)\s*:\s*(.+)$') { $datos.Perfil = $Matches[2].Trim() }
        elseif ($linea -match '^\s*(Canal|Channel)\s*:\s*(\d+)') { $datos.Canal = [int]$Matches[2] }
        elseif ($linea -match '^\s*(Estado|State)\s*:\s*(.+)$') { $datos.Estado = $Matches[2].Trim() }
    }
    if ($datos.Estado -notmatch '^(conectado|connected)$' -or -not $datos.Ssid) { return $null }
    return $datos
}
function Clave-Guardada($perfil) {
    # Windows guarda la clave de las redes a las que ya se conectó y la muestra sin pedir administrador
    foreach ($linea in (cmd /c "netsh wlan show profile name=`"$perfil`" key=clear" 2>$null)) {
        if ($linea -match '(Contenido de la clave|Key Content)\s*:\s*(.*)$') { return $Matches[2].Trim() }
    }
    return $null
}
function Buscar-Robot {
    $placa = Get-CimInstance Win32_PnPEntity -Filter "Name LIKE '%(COM%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "CP210|CH340|CH910|USB.*(Serial|UART)|Silicon Labs" } | Select-Object -First 1
    if ($placa -and $placa.Name -match '\((COM\d+)\)') { return $Matches[1] }
    return $null
}

function Mostrar-Estado {
    Clear-Host
    Write-Host "  A R I E S   -   GeoExpoFísica 2026" -ForegroundColor Cyan
    Write-Host ""
    $wifi = Wifi-PC
    if ($wifi) {
        $banda = if ($wifi.Canal -gt 14) { "5 GHz: el robot NO la puede usar" } else { "2,4 GHz" }
        Write-Host "  WiFi de esta computadora: $($wifi.Ssid) ($banda)"
    } else {
        Write-Host "  WiFi de esta computadora: no está conectada a una WiFi" -ForegroundColor Yellow
    }
    if (Hay-Internet) { Write-Host "  Internet: sí" -ForegroundColor Green }
    else { Write-Host "  Internet: NO (Aries funciona, pero sin charla, Wikipedia ni clima)" -ForegroundColor Yellow }
    $com = Buscar-Robot
    Write-Host "  Robot por USB: $(if ($com) { "conectado en $com" } else { 'no conectado' })"
    Write-Host "  Programa instalado: $(if ($script:instalado) { 'sí' } else { 'NO (elige 6)' })" `
        -ForegroundColor $(if ($script:instalado) { "Gray" } else { "Yellow" })
    if (-not (Hay-ClaveGroq)) { Write-Host "  Clave de Groq: falta (elige 7)" -ForegroundColor Yellow }
    Write-Host "  Aries: $(if (Cerebro-Encendido) { 'ENCENDIDO' } else { 'apagado' })"
    Write-Host ""
    Write-Host "  1) Encender Aries (gráficas + lo que escucha)"
    Write-Host "  2) Conectar el robot a la WiFi de esta computadora (por USB)"
    Write-Host "  3) Conectar el robot a otra red WiFi (por USB)"
    Write-Host "  4) Ver las redes que recuerda el robot"
    Write-Host "  5) Apagar Aries"
    Write-Host "  6) Instalar o reparar (la primera vez en cada computadora)"
    Write-Host "  7) Poner la clave de Groq (internet)"
    Write-Host "  8) Cargar el firmware al robot"
    Write-Host "  0) Salir"
}

# --- Hablar con el robot por USB ---
function Abrir-Robot {
    $com = Buscar-Robot
    if (-not $com) {
        Write-Host "No encuentro el robot por USB." -ForegroundColor Yellow
        Write-Host "Conéctalo con el cable USB (antes desconecta el cable 55c -> VIN: nunca los dos a la vez)."
        return $null
    }
    $puerto = New-Object System.IO.Ports.SerialPort $com, 115200
    $puerto.Encoding = [System.Text.Encoding]::UTF8
    $puerto.NewLine = "`n"
    $puerto.ReadTimeout = 200
    try { $puerto.Open() } catch {
        Write-Host "El puerto $com está ocupado: cierra el monitor serial (Arduino) o el programa que lo use." -ForegroundColor Yellow
        return $null
    }
    return $puerto
}
function Leer-Linea($puerto) {
    try { return $puerto.ReadLine().Trim() } catch [System.TimeoutException] { return $null } catch { return $null }
}
# Manda el comando cada 4 s (el robot puede estar arrancando) hasta que conteste lo esperado
function Mandar-Hasta($puerto, $comando, $esperado, $segundos) {
    $fin = (Get-Date).AddSeconds($segundos)
    $proximo = Get-Date
    while ((Get-Date) -lt $fin) {
        if ((Get-Date) -ge $proximo) {
            $puerto.Write("`n$comando`n")
            $proximo = (Get-Date).AddSeconds(4)
        }
        $linea = Leer-Linea $puerto
        if ($linea -and $linea -match $esperado) { return $linea }
    }
    return $null
}

function Ensenar-Red($nombre, $clave) {
    if ($nombre -match '\|') { Write-Host "El nombre de la red no puede tener el signo |" -ForegroundColor Yellow; return }
    $puerto = Abrir-Robot
    if (-not $puerto) { return }
    try {
        Write-Host "Le enseño la red `"$nombre`" al robot..."
        if (-not (Mandar-Hasta $puerto "wifi $nombre|$clave" '^WIFI GUARDADA' 30)) {
            Write-Host "El robot no contestó. ¿Tiene cargado el firmware nuevo? (opción 8)" -ForegroundColor Yellow
            return
        }
        Write-Host "Guardada. El robot se reinicia y se conecta (hasta 1 minuto)..." -ForegroundColor Green
        $fin = (Get-Date).AddSeconds(75)
        while ((Get-Date) -lt $fin) {
            $linea = Leer-Linea $puerto
            if (-not $linea -or $linea -match '\|') { continue }  # la línea con la clave no se muestra
            if ($linea -match 'motivo (15|202|204)') { Write-Host "  La red rechaza la clave: revísala." -ForegroundColor Yellow }
            elseif ($linea -match 'motivo 201') { Write-Host "  El robot no ve la red (¿es de 5 GHz o está lejos?)" -ForegroundColor Yellow }
            elseif ($linea -match 'Conectando a WiFi|Conectado\. IP|cerebro|Servidor:') { Write-Host "  $linea" }
            if ($linea -match 'ERROR: no se pudo conectar') {
                Write-Host "  No se pudo conectar. Revisa la clave y que la red sea de 2,4 GHz." -ForegroundColor Red
                Write-Host "  (iPhone: Ajustes > Compartir Internet > activa 'Maximizar compatibilidad')"
                return
            }
            if ($linea -match 'Conectado al servidor de Aries') {
                Write-Host "`nListo: el robot está conectado a Aries." -ForegroundColor Green
                Write-Host "Ya puedes desconectar el USB y usar las pilas (cable 55c -> VIN + interruptor)."
                return
            }
            if ($linea -match 'Servidor: ws') {
                if (-not (Cerebro-Encendido)) {
                    Write-Host "`nListo: el robot quedó en la WiFi. Enciende Aries (opción 1) y se conecta solo." -ForegroundColor Green
                    return
                }
                $fin = (Get-Date).AddSeconds(15)  # el cerebro está encendido: falta que se conecte
            }
        }
        Write-Host "El robot guardó la red, pero no vi que terminara de conectarse. Mira la opción 4." -ForegroundColor Yellow
    } finally { $puerto.Close() }
}

function Red-De-Esta-PC {
    $wifi = Wifi-PC
    if (-not $wifi) {
        Write-Host "Esta computadora no está en una WiFi. Conéctala desde el ícono de WiFi (abajo a la derecha)"
        Write-Host "a la red que van a usar, o elige 3 para escribir la red a mano."
        return
    }
    if ($wifi.Canal -gt 14) {
        Write-Host "`"$($wifi.Ssid)`" es de 5 GHz y el ESP32 solo usa 2,4 GHz." -ForegroundColor Yellow
        Write-Host "Si el router tiene otra red de 2,4 GHz, conecta la PC a esa. En un iPhone: activa 'Maximizar compatibilidad'."
        if ((Read-Host "¿Intentar igual? (s/n)") -notmatch '^s') { return }
    }
    $clave = if ($wifi.Perfil) { Clave-Guardada $wifi.Perfil } else { $null }
    if ($null -eq $clave) { $clave = Read-Host "No pude leer la clave de `"$($wifi.Ssid)`". Escríbela" }
    Ensenar-Red $wifi.Ssid $clave
}

function Otra-Red {
    $vistas = @(netsh wlan show networks 2>$null | ForEach-Object { if ($_ -match '^SSID \d+\s*:\s*(.+)$') { $Matches[1].Trim() } } |
        Where-Object { $_ } | Select-Object -Unique)
    for ($i = 0; $i -lt $vistas.Count; $i++) { Write-Host "  $($i + 1)) $($vistas[$i])" }
    $eleccion = Read-Host "Número de la red (o escribe su nombre)"
    $nombre = if ($eleccion -match '^\d+$' -and [int]$eleccion -ge 1 -and [int]$eleccion -le $vistas.Count) {
        $vistas[[int]$eleccion - 1]
    } else { $eleccion.Trim() }
    if (-not $nombre) { return }
    $clave = Clave-Guardada $nombre
    if ($null -eq $clave) { $clave = Read-Host "Clave de `"$nombre`" (Enter si no tiene)" }
    Ensenar-Red $nombre $clave
}

function Redes-Del-Robot {
    $puerto = Abrir-Robot
    if (-not $puerto) { return }
    try {
        if (-not (Mandar-Hasta $puerto "wifi lista" '^REDES CONOCIDAS' 20)) {
            Write-Host "El robot no contestó. ¿Tiene cargado el firmware nuevo? (opción 8)" -ForegroundColor Yellow
            return
        }
        $fin = (Get-Date).AddSeconds(2)
        while ((Get-Date) -lt $fin) {
            $linea = Leer-Linea $puerto
            if ($linea -match '^RED: (.+)') { Write-Host "  - $($Matches[1])" }
            elseif ($linea -match '^WIFI ACTUAL: (.+)') { Write-Host "  Conectado ahora a: $($Matches[1])"; break }
        }
    } finally { $puerto.Close() }
}

function Poner-ClaveGroq {
    Write-Host "La clave se saca gratis en https://console.groq.com/keys (empieza con gsk_)."
    $clave = (Read-Host "Pega la clave de Groq (Enter para cancelar)").Trim()
    if (-not $clave) { return }
    $otras = if (Test-Path $archivoClave) { @(Get-Content $archivoClave | Where-Object { $_ -notmatch '^\s*GROQ_API_KEY\s*=' }) } else { @() }
    Set-Content -Path $archivoClave -Value ($otras + "GROQ_API_KEY=$clave") -Encoding ASCII
    Write-Host "Clave guardada en robot-ia\.env (no se sube a git)." -ForegroundColor Green
    if (Cerebro-Encendido) { Write-Host "Apaga y vuelve a encender Aries para que la use." }
}

function Cargar-Firmware {
    if (-not (Get-Command arduino-cli -ErrorAction SilentlyContinue)) {
        Write-Host "Falta arduino-cli: primero elige 6 (Instalar)." -ForegroundColor Yellow
        return
    }
    $com = Buscar-Robot
    if (-not $com) {
        Write-Host "Conecta el robot por USB (antes desconecta el cable 55c -> VIN: nunca los dos a la vez)." -ForegroundColor Yellow
        return
    }
    Write-Host "Cargando el firmware en $com (tarda 1 o 2 minutos)..."
    arduino-cli compile --upload -p $com --fqbn esp32:esp32:esp32 (Join-Path $PSScriptRoot "firmware\robot_wifi")
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nFirmware cargado. Las redes que el robot ya conocía se mantienen." -ForegroundColor Green
        Write-Host "Si en esta computadora todavía no le enseñaste la WiFi, elige 2."
    } else {
        Write-Host "`nNo se pudo cargar. Desconecta y vuelve a conectar el USB e inténtalo otra vez." -ForegroundColor Red
    }
}

# --- Menú ---
$script:instalado = Esta-Instalado
while ($true) {
    Mostrar-Estado
    $opcion = Read-Host "`nElige una opción"
    switch ($opcion) {
        "1" {
            if (-not $script:instalado) { Write-Host "Primero instala (opción 6)." -ForegroundColor Yellow; Pausa; break }
            Start-Process (Join-Path $PSScriptRoot "iniciar.bat")
            Write-Host "Aries se está encendiendo en otra ventana. Si el robot no se conecta en 30 s, elige 2." -ForegroundColor Green
            Pausa
        }
        "2" { Titulo "Robot a la WiFi de esta computadora"; Red-De-Esta-PC; Pausa }
        "3" { Titulo "Robot a otra red"; Otra-Red; Pausa }
        "4" { Titulo "Redes del robot"; Redes-Del-Robot; Pausa }
        "5" { & (Join-Path $PSScriptRoot "apagar.bat"); Write-Host "Aries apagado."; Pausa }
        "6" {
            Titulo "Instalar"
            Start-Process (Join-Path $PSScriptRoot "instalar.bat") -Wait
            $script:instalado = Esta-Instalado
        }
        "7" { Titulo "Clave de Groq"; Poner-ClaveGroq; Pausa }
        "8" { Titulo "Firmware"; Cargar-Firmware; Pausa }
        "0" { exit }
    }
}
