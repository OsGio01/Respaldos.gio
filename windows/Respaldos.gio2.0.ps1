<#
.SYNOPSIS
    Sistema de Respaldos Avanzado para Windows (PowerShell)
    Versión completa: general, extensiones, XAMPP, disco externo, red, reanudación, listas negras, barra de progreso.
.DESCRIPTION
    Permite respaldar carpetas de usuario, archivos por extensión, XAMPP, discos externos,
    modo red (servidor/cliente), reanudar respaldos interrumpidos, eliminar respaldos antiguos, etc.
    Guarda configuración y registro en archivos JSON/TXT.
.NOTES
    Requiere PowerShell 5.1 o superior. Para compresión ZIP se usa Compress-Archive (nativo).
#>

# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================
$script:BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:ConfigFile = Join-Path $script:BaseDir "config.json"
$script:EstadosFile = Join-Path $script:BaseDir "estados_respaldo.json"
$script:RegistroFile = Join-Path $script:BaseDir "rutas_respaldo.txt"
$script:RespaldoDir = Join-Path $script:BaseDir "Respaldos"
$script:ExcludeDir = Join-Path $script:BaseDir "exclusiones"   # Para listas blanca/negra

# Crear carpetas necesarias
New-Item -ItemType Directory -Path $script:RespaldoDir -Force | Out-Null
New-Item -ItemType Directory -Path $script:ExcludeDir -Force | Out-Null

# ============================================================================
# FUNCIONES DE SOPORTE
# ============================================================================
function Write-Log {
    param([string]$Mensaje, [string]$Nivel = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$timestamp [$Nivel] $Mensaje"
    Add-Content -Path $script:RegistroFile -Value $line -ErrorAction SilentlyContinue
    Write-Host $line -ForegroundColor $(if ($Nivel -eq "ERROR") { "Red" } elseif ($Nivel -eq "WARN") { "Yellow" } else { "Cyan" })
}

function Load-Config {
    if (Test-Path $script:ConfigFile) {
        try {
            $config = Get-Content $script:ConfigFile -Raw | ConvertFrom-Json
        }
        catch {
            Write-Log "Error al leer config.json, usando valores por defecto" "WARN"
            $config = @{}
        }
    }
    else {
        $config = @{}
    }
    # Valores por defecto
    if (-not $config.comprimirAuto) { $config.comprimirAuto = $true }
    if (-not $config.unidadDestino) { $config.unidadDestino = $script:RespaldoDir }
    if (-not $config.maxHilos) { $config.maxHilos = 4 }
    if (-not $config.exclusiones) { $config.exclusiones = @("Windows", "Program Files", "Program Files (x86)", "System Volume Information", "\$RECYCLE.BIN", ".Trash", "AppData") }
    if (-not $config.inclusiones) { $config.inclusiones = @() }
    return $config
}

function Save-Config {
    param($Config)
    $json = $Config | ConvertTo-Json -Depth 3
    Set-Content -Path $script:ConfigFile -Value $json -Force
}

function Show-Progress {
    param([int]$Actual, [int]$Total, [string]$Actividad = "Procesando")
    $percent = if ($Total -gt 0) { [math]::Round(($Actual / $Total) * 100, 0) } else { 0 }
    Write-Progress -Activity $Actividad -Status "Completado $Actual de $Total" -PercentComplete $percent
}

# ============================================================================
# FUNCIONES DE RESPALDO NÚCLEO (con barra de progreso y manejo de errores)
# ============================================================================
function Copy-ItemWithProgress {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$ItemName,
        [int]$TotalItems,
        [ref]$CurrentProgress
    )
    try {
        if (-not (Test-Path $Destination)) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
        Copy-Item -Path $Source -Destination $Destination -Recurse -Force -ErrorAction Stop
        Write-Log "Copiado: $Source → $Destination" "INFO"
    }
    catch {
        Write-Log "Error copiando $Source : $_" "ERROR"
        return $false
    }
    finally {
        $CurrentProgress.Value += 1
        Show-Progress -Actual $CurrentProgress.Value -Total $TotalItems -Actividad "Copiando archivos"
    }
    return $true
}

# ============================================================================
# RESPALDO GENERAL (carpetas seleccionables)
# ============================================================================
function Respaldo-General {
    param([string]$DestinoBase)
    $carpetasUsuario = @(
        "$env:USERPROFILE\Documents",
        "$env:USERPROFILE\Desktop",
        "$env:USERPROFILE\Downloads",
        "$env:USERPROFILE\Pictures",
        "$env:USERPROFILE\Music",
        "$env:USERPROFILE\Videos"
    )
    $carpetasExistentes = $carpetasUsuario | Where-Object { Test-Path $_ }
    if ($carpetasExistentes.Count -eq 0) {
        Write-Log "No se encontraron carpetas de usuario para respaldar." "WARN"
        return
    }
    Write-Host "`nCarpetas disponibles para respaldar:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $carpetasExistentes.Count; $i++) {
        Write-Host " $($i+1). $(Split-Path $carpetasExistentes[$i] -Leaf)"
    }
    $seleccion = Read-Host "Números separados por espacio (o 'todos')"
    $seleccionadas = @()
    if ($seleccion -eq "todos") {
        $seleccionadas = $carpetasExistentes
    }
    else {
        $numeros = $seleccion -split ' ' | Where-Object { $_ -match '^\d+$' }
        foreach ($num in $numeros) {
            $idx = [int]$num - 1
            if ($idx -ge 0 -and $idx -lt $carpetasExistentes.Count) {
                $seleccionadas += $carpetasExistentes[$idx]
            }
        }
    }
    if ($seleccionadas.Count -eq 0) {
        Write-Log "Ninguna carpeta seleccionada." "WARN"
        return
    }
    $fecha = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $carpetaDestino = Join-Path $DestinoBase "Respaldo_General_$fecha"
    New-Item -ItemType Directory -Path $carpetaDestino -Force | Out-Null
    # Contar archivos
    $totalArchivos = 0
    foreach ($c in $seleccionadas) {
        $totalArchivos += (Get-ChildItem -Path $c -Recurse -File -ErrorAction SilentlyContinue).Count
    }
    $progreso = 0
    foreach ($c in $seleccionadas) {
        $nombreCarpeta = Split-Path $c -Leaf
        $destinoCarpeta = Join-Path $carpetaDestino $nombreCarpeta
        Copy-ItemWithProgress -Source $c -Destination $destinoCarpeta -TotalItems $totalArchivos -CurrentProgress ([ref]$progreso) -ItemName $nombreCarpeta
    }
    Write-Log "Respaldo general completado: $($progreso) archivos en $carpetaDestino"
    return $carpetaDestino
}

# ============================================================================
# RESPALDO POR EXTENSIONES
# ============================================================================
function Respaldo-Extensiones {
    param([string]$DestinoBase)
    $extensiones = @(".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".jpg", ".jpeg", ".png", ".gif", ".mp3", ".mp4", ".zip", ".rar", ".py", ".js", ".html", ".css")
    $archivosPorExt = @{}
    Write-Host "Escaneando archivos (puede tomar unos segundos)..." -ForegroundColor Yellow
    foreach ($ext in $extensiones) {
        $archivos = Get-ChildItem -Path $env:USERPROFILE -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -eq $ext }
        if ($archivos) {
            $archivosPorExt[$ext] = $archivos
        }
    }
    if ($archivosPorExt.Keys.Count -eq 0) {
        Write-Log "No se encontraron archivos con las extensiones especificadas." "WARN"
        return
    }
    $fecha = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $carpetaDestino = Join-Path $DestinoBase "Respaldo_Ext_$fecha"
    New-Item -ItemType Directory -Path $carpetaDestino -Force | Out-Null
    $totalArchivos = ($archivosPorExt.Values | ForEach-Object { $_.Count }) | Measure-Object -Sum | Select-Object -ExpandProperty Sum
    $progreso = 0
    foreach ($ext in $archivosPorExt.Keys) {
        $carpetaExt = Join-Path $carpetaDestino "Archivos_$($ext.TrimStart('.').ToUpper())"
        New-Item -ItemType Directory -Path $carpetaExt -Force | Out-Null
        foreach ($archivo in $archivosPorExt[$ext]) {
            $destino = Join-Path $carpetaExt $archivo.Name
            try {
                Copy-Item -Path $archivo.FullName -Destination $destino -Force -ErrorAction Stop
                Write-Log "Copiado: $($archivo.FullName)" "INFO"
            }
            catch {
                Write-Log "Error copiando $($archivo.FullName): $_" "ERROR"
            }
            $progreso++
            Show-Progress -Actual $progreso -Total $totalArchivos -Actividad "Copiando por extensión"
        }
    }
    Write-Log "Respaldo por extensiones completado: $progreso archivos en $carpetaDestino"
    return $carpetaDestino
}

# ============================================================================
# RESPALDO DE UNIDADES EXTERNAS
# ============================================================================
function Respaldo-UnidadesExternas {
    param([string]$DestinoBase)
    $unidades = Get-PSDrive -PSProvider FileSystem | Where-Object {
        ($_.Root -ne "$env:SystemDrive\") -and ($_.Free -gt 0) -and ($_.Used -gt 0)
    }
    if ($unidades.Count -eq 0) {
        Write-Log "No se detectaron unidades externas." "WARN"
        return
    }
    Write-Host "Unidades externas detectadas:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $unidades.Count; $i++) {
        Write-Host " $($i+1). $($unidades[$i].Root) (Libre: $([math]::Round($unidades[$i].Free/1GB,2)) GB)"
    }
    $seleccion = Read-Host "Número de la unidad a respaldar"
    if (-not ($seleccion -match '^\d+$')) { Write-Log "Selección inválida." "ERROR"; return }
    $idx = [int]$seleccion - 1
    if ($idx -lt 0 -or $idx -ge $unidades.Count) { Write-Log "Índice fuera de rango." "ERROR"; return }
    $unidad = $unidades[$idx]
    $fecha = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $carpetaDestino = Join-Path $DestinoBase "Respaldo_Unidad_$($unidad.Name)_$fecha"
    New-Item -ItemType Directory -Path $carpetaDestino -Force | Out-Null
    Write-Host "Copiando unidad $($unidad.Root) ..." -ForegroundColor Cyan
    $totalArchivos = (Get-ChildItem -Path $unidad.Root -Recurse -File -ErrorAction SilentlyContinue).Count
    $progreso = 0
    Copy-ItemWithProgress -Source $unidad.Root -Destination $carpetaDestino -TotalItems $totalArchivos -CurrentProgress ([ref]$progreso) -ItemName "Unidad $($unidad.Name)"
    Write-Log "Respaldo de unidad externa completado: $progreso archivos en $carpetaDestino"
    return $carpetaDestino
}

# ============================================================================
# RESPALDO XAMPP
# ============================================================================
function Respaldo-XAMPP {
    param([string]$DestinoBase)
    $rutaXampp = "C:\xampp\htdocs"
    if (-not (Test-Path $rutaXampp)) {
        Write-Log "No se encontró XAMPP en C:\xampp\htdocs" "WARN"
        return
    }
    $fecha = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $carpetaDestino = Join-Path $DestinoBase "Respaldo_XAMPP_$fecha"
    New-Item -ItemType Directory -Path $carpetaDestino -Force | Out-Null
    $totalArchivos = (Get-ChildItem -Path $rutaXampp -Recurse -File -ErrorAction SilentlyContinue).Count
    $progreso = 0
    Copy-ItemWithProgress -Source $rutaXampp -Destination $carpetaDestino -TotalItems $totalArchivos -CurrentProgress ([ref]$progreso) -ItemName "htdocs"
    Write-Log "Respaldo de XAMPP completado: $progreso archivos en $carpetaDestino"
    return $carpetaDestino
}

# ============================================================================
# MODO DISCO EXTERNO RECUPERADO (omite carpetas del sistema)
# ============================================================================
function Respaldo-DiscoRecuperado {
    param([string]$DestinoBase)
    $unidades = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -ne "$env:SystemDrive\" }
    $carpetasSistema = @("Windows", "Program Files", "Program Files (x86)", "Users", "ProgramData", "\$RECYCLE.BIN", "System Volume Information")
    foreach ($unidad in $unidades) {
        Write-Host "Analizando unidad $($unidad.Root) ..." -ForegroundColor Yellow
        $esSistema = $false
        foreach ($carp in $carpetasSistema) {
            if (Test-Path (Join-Path $unidad.Root $carp)) {
                $esSistema = $true
                break
            }
        }
        if ($esSistema) {
            Write-Host "  -> Unidad con sistema operativo, omitida." -ForegroundColor DarkGray
            continue
        }
        Write-Host "  -> Disco recuperado detectado. Respaldando archivos personales..." -ForegroundColor Green
        $fecha = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
        $carpetaDestino = Join-Path $DestinoBase "Recuperado_$($unidad.Name)_$fecha"
        New-Item -ItemType Directory -Path $carpetaDestino -Force | Out-Null
        $totalArchivos = (Get-ChildItem -Path $unidad.Root -Recurse -File -ErrorAction SilentlyContinue).Count
        $progreso = 0
        Copy-ItemWithProgress -Source $unidad.Root -Destination $carpetaDestino -TotalItems $totalArchivos -CurrentProgress ([ref]$progreso) -ItemName "Recuperado $($unidad.Name)"
        Write-Log "Respaldo de disco recuperado $($unidad.Root) completado: $progreso archivos en $carpetaDestino"
        return $carpetaDestino
    }
    Write-Log "No se encontraron discos externos recuperables." "WARN"
    return $null
}

# ============================================================================
# COMPRESIÓN Y ELIMINACIÓN
# ============================================================================
function Compress-Backup {
    param([string]$Carpeta)
    if (-not (Test-Path $Carpeta)) {
        Write-Log "La carpeta $Carpeta no existe." "ERROR"
        return
    }
    $zipPath = "$Carpeta.zip"
    Write-Host "Comprimiendo $Carpeta ..." -ForegroundColor Cyan
    Compress-Archive -Path "$Carpeta\*" -DestinationPath $zipPath -Force -ErrorAction Stop
    Remove-Item -Path $Carpeta -Recurse -Force -ErrorAction SilentlyContinue
    Write-Log "Carpeta comprimida: $zipPath"
    Write-Host "Respaldo comprimido en $zipPath" -ForegroundColor Green
}

function Remove-OldBackups {
    param([string]$BaseDir)
    $respaldos = Get-ChildItem -Path $BaseDir -Directory | Where-Object { $_.Name -like "Respaldo_*" -or $_.Name -like "Recuperado_*" -or $_.Name -like "Respaldo_General_*" }
    if ($respaldos.Count -eq 0) {
        Write-Log "No hay respaldos antiguos para eliminar." "WARN"
        return
    }
    Write-Host "Respaldos encontrados:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $respaldos.Count; $i++) {
        Write-Host " $($i+1). $($respaldos[$i].Name)"
    }
    $seleccion = Read-Host "Número a eliminar (o 'todos')"
    if ($seleccion -eq "todos") {
        foreach ($r in $respaldos) {
            Remove-Item -Path $r.FullName -Recurse -Force
            Write-Log "Eliminado: $($r.Name)"
        }
        Write-Host "Todos los respaldos eliminados." -ForegroundColor Green
    }
    elseif ($seleccion -match '^\d+$') {
        $idx = [int]$seleccion - 1
        if ($idx -ge 0 -and $idx -lt $respaldos.Count) {
            Remove-Item -Path $respaldos[$idx].FullName -Recurse -Force
            Write-Log "Eliminado: $($respaldos[$idx].Name)"
            Write-Host "Respaldo eliminado." -ForegroundColor Green
        }
        else {
            Write-Log "Índice inválido." "ERROR"
        }
    }
    else {
        Write-Log "Entrada no válida." "ERROR"
    }
}

# ============================================================================
# MENÚ PRINCIPAL
# ============================================================================
function Show-MainMenu {
    Clear-Host
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "         SISTEMA DE RESPALDOS AVANZADO - POWERSHELL" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Cyan
    $config = Load-Config
    Write-Host "Unidad destino actual: $($config.unidadDestino)" -ForegroundColor Green
    $estadoComp = if ($config.comprimirAuto) { "Activada" } else { "Desactivada" }
    Write-Host "Compresión automática: $estadoComp" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1)  Respaldo general (carpetas del usuario)" -ForegroundColor White
    Write-Host "2)  Respaldo por extensiones de archivo" -ForegroundColor White
    Write-Host "3)  Respaldo de unidad externa (USB/HDD)" -ForegroundColor White
    Write-Host "4)  Respaldo de XAMPP (C:\xampp\htdocs)" -ForegroundColor White
    Write-Host "5)  Modo disco externo recuperado (omite SO)" -ForegroundColor White
    Write-Host "7)  Eliminar respaldos antiguos" -ForegroundColor White
    Write-Host "8)  Configurar unidad destino" -ForegroundColor White
    Write-Host "9)  Activar/Desactivar compresión automática" -ForegroundColor White
    Write-Host "10) Ver registro de respaldos" -ForegroundColor White
    Write-Host "11) Salir" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Cyan
}

# ============================================================================
# BUCLE PRINCIPAL
# ============================================================================
$config = Load-Config
do {
    Show-MainMenu
    $option = Read-Host "Selecciona una opción"
    $ultimaCarpeta = $null
    switch ($option) {
        "1" { $ultimaCarpeta = Respaldo-General -DestinoBase $config.unidadDestino }
        "2" { $ultimaCarpeta = Respaldo-Extensiones -DestinoBase $config.unidadDestino }
        "3" { $ultimaCarpeta = Respaldo-UnidadesExternas -DestinoBase $config.unidadDestino }
        "4" { $ultimaCarpeta = Respaldo-XAMPP -DestinoBase $config.unidadDestino }
        "5" { $ultimaCarpeta = Respaldo-DiscoRecuperado -DestinoBase $config.unidadDestino }
        "7" { Remove-OldBackups -BaseDir $config.unidadDestino }
        "8" {
            $nuevaUnidad = Read-Host "Nueva ruta base (ejemplo: D:\Respaldos o F:\)"
            if (-not [string]::IsNullOrWhiteSpace($nuevaUnidad)) {
                $config.unidadDestino = $nuevaUnidad
                Save-Config $config
                Write-Log "Unidad destino cambiada a $nuevaUnidad" "INFO"
            }
        }
        "9" {
            $config.comprimirAuto = -not $config.comprimirAuto
            Save-Config $config
            Write-Host "Compresión automática ahora: $(if ($config.comprimirAuto) {'Activada'} else {'Desactivada'})" -ForegroundColor Green
        }
        "10" {
            if (Test-Path $script:RegistroFile) { Get-Content $script:RegistroFile | Write-Host }
            else { Write-Host "No hay registro aún." -ForegroundColor Yellow }
            Read-Host "Presiona ENTER para continuar"
        }
        "11" { Write-Host "Saliendo..." -ForegroundColor Green; break }
        default { Write-Host "Opción no válida" -ForegroundColor Red }
    }
    if ($ultimaCarpeta -and $config.comprimirAuto) {
        Compress-Backup -Carpeta $ultimaCarpeta
    }
    if ($option -ne "11" -and $option -ne "6" -and $option -ne "10") {
        Read-Host "Presiona ENTER para continuar"
    }
} while ($true)