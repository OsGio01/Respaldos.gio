<#
.SYNOPSIS
    Respaldos.Gio - version minima de terminal (sin Python).
.DESCRIPTION
    Respaldo general, reanudar y eliminar. Sin modo red, sin deduplicacion por
    hash, sin extensiones, sin interfaz grafica: es la version portatil para
    equipos donde no hay Python instalado.
.NOTES
    Requiere Windows PowerShell 5.1 o superior. Sin dependencias externas.
    Los scripts de Linux (Linux/respaldos.sh) y macOS (macOS/respaldos.sh) son
    casi iguales a este: si cambias uno, cambia los otros.
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfFile = Join-Path $ScriptDir "respaldos.conf"
$StateFile = Join-Path $ScriptDir "respaldos.estado"

# ---------------------------------------------------------------- presentacion
function Escribir-Info { param([string]$Texto) Write-Host $Texto }
function Escribir-Titulo {
    param([string]$Texto)
    Write-Host ""
    Write-Host "=== $Texto ===" -ForegroundColor Cyan
}
function Escribir-Aviso { param([string]$Texto) Write-Host $Texto -ForegroundColor Yellow }
function Escribir-Error { param([string]$Texto) Write-Host $Texto -ForegroundColor Red }

# ---------------------------------------------------------------- configuracion
function Leer-Destino {
    $destino = Join-Path $ScriptDir "Respaldos"
    if (Test-Path $ConfFile) {
        foreach ($linea in Get-Content $ConfFile -Encoding UTF8) {
            if ($linea -match '^\s*DESTINO\s*=\s*(.+)$') { $destino = $Matches[1].Trim() }
        }
    }
    return $destino
}

function Guardar-Destino {
    param([string]$Destino)
    $contenido = @("# Respaldos.Gio - configuracion minima", "DESTINO=$Destino")
    Set-Content -Path $ConfFile -Value $contenido -Encoding UTF8
}

# ---------------------------------------------------------------- carpetas
function Obtener-Carpeta {
    param([string]$Id, [string]$Etiqueta)
    try { $ruta = [Environment]::GetFolderPath($Id) } catch { $ruta = "" }
    if ($ruta -and (Test-Path $ruta)) {
        return @{ Etiqueta = $Etiqueta; Ruta = $ruta }
    }
    return $null
}

function Carpetas-Usuario {
    $carpetas = @()
    # Si esta definida RESPALDOS_GIO_FUENTES se usa esa lista en lugar de
    # detectar las carpetas del usuario. Formato: "Etiqueta|ruta;Etiqueta|ruta"
    if ($env:RESPALDOS_GIO_FUENTES) {
        foreach ($par in $env:RESPALDOS_GIO_FUENTES.Split(";")) {
            if (-not $par) { continue }
            $partes = $par.Split("|", 2)
            if ($partes.Count -lt 2) { continue }
            if (Test-Path $partes[1]) {
                $carpetas += @{ Etiqueta = $partes[0]; Ruta = $partes[1] }
            }
        }
        return $carpetas
    }
    $candidatas = @(
        (Obtener-Carpeta "MyDocuments" "Documentos"),
        (Obtener-Carpeta "Desktop" "Escritorio"),
        (Obtener-Carpeta "MyPictures" "Imagenes"),
        (Obtener-Carpeta "MyMusic" "Musica"),
        (Obtener-Carpeta "MyVideos" "Videos")
    )
    $descargas = Join-Path $env:USERPROFILE "Downloads"
    if (Test-Path $descargas) {
        $candidatas += @{ Etiqueta = "Descargas"; Ruta = $descargas }
    }
    foreach ($c in $candidatas) {
        if ($c -ne $null) { $carpetas += $c }
    }
    return $carpetas
}

# ---------------------------------------------------------------- estado
function Leer-Estado {
    $estado = @{ Valido = $false; Carpeta = ""; Fuentes = @(); Copias = @() }
    if (-not (Test-Path $StateFile)) { return $estado }
    foreach ($linea in Get-Content $StateFile -Encoding UTF8) {
        if ($linea -match '^\s*CARPETA\s*=\s*(.+)$') {
            $estado.Carpeta = $Matches[1].Trim(); $estado.Valido = $true
        } elseif ($linea -match '^\s*FUENTE\s*=\s*(.+)$') {
            $estado.Fuentes += $Matches[1].Trim()
        } elseif ($linea -match '^\s*COPIA\s*=\s*(.+)$') {
            $estado.Copias += $Matches[1].Trim()
        }
    }
    if ($estado.Fuentes.Count -eq 0) { $estado.Valido = $false }
    return $estado
}

function Escribir-Estado {
    param([string]$Carpeta, [string[]]$Fuentes, [string[]]$Copias)
    $contenido = @("# Respaldos.Gio - estado de reanudacion", "CARPETA=$Carpeta")
    foreach ($f in $Fuentes) { $contenido += "FUENTE=$f" }
    foreach ($c in $Copias) { $contenido += "COPIA=$c" }
    Set-Content -Path $StateFile -Value $contenido -Encoding UTF8
}

function Agregar-Copia {
    param([string]$Ruta)
    Add-Content -Path $StateFile -Value "COPIA=$Ruta" -Encoding UTF8
}

# ---------------------------------------------------------------- copia
function Listar-Archivos {
    param([string]$Raiz)
    $lista = @()
    if (-not (Test-Path $Raiz)) { return $lista }
    $archivos = Get-ChildItem -Path $Raiz -Recurse -File -Force -ErrorAction SilentlyContinue
    foreach ($a in $archivos) {
        $relativo = $a.FullName.Substring($Raiz.Length).TrimStart('\', '/')
        $lista += ,@($a.FullName, $relativo)
    }
    return $lista
}

function Copiar-Arbol {
    param([string[]]$Fuentes, [string]$DestinoCarpeta, [string[]]$YaCopiados, [switch]$Reanudando)
    $copias = New-Object System.Collections.ArrayList
    foreach ($c in $YaCopiados) { [void]$copias.Add($c) }

    $pendientes = @()
    foreach ($fuente in $Fuentes) {
        $partes = $fuente.Split("|", 2)
        if ($partes.Count -lt 2) { continue }
        $etiqueta = $partes[0]
        $raiz = $partes[1]
        foreach ($par in Listar-Archivos $raiz) {
            $clave = "$etiqueta/$($par[1])"
            if ($copias -contains $clave) { continue }
            $pendientes += ,@($etiqueta, $par[0], $clave)
        }
    }

    $total = $pendientes.Count
    Escribir-Info "Archivos a copiar: $total"
    if ($total -eq 0) { return $copias }

    $hechos = 0
    foreach ($p in $pendientes) {
        $destinoArchivo = Join-Path $DestinoCarpeta (Join-Path $p[0] $p[2].Substring($p[0].Length + 1))
        $carpetaDestino = Split-Path -Parent $destinoArchivo
        if (-not (Test-Path $carpetaDestino)) { New-Item -ItemType Directory -Path $carpetaDestino -Force | Out-Null }
        Copy-Item -LiteralPath $p[1] -Destination $destinoArchivo -Force
        [void]$copias.Add($p[2])
        Agregar-Copia $p[2]
        $hechos++
        if ($hechos % 25 -eq 0 -or $hechos -eq $total) {
            Write-Host ("  {0}/{1} archivos" -f $hechos, $total) -ForegroundColor DarkGray
        }
    }
    return $copias
}

function Comprimir-Respaldo {
    param([string]$Carpeta)
    $zip = "$Carpeta.zip"
    Escribir-Info "Comprimiendo en $(Split-Path -Leaf $zip) ..."
    try {
        Compress-Archive -Path (Join-Path $Carpeta "*") -DestinationPath $zip -Force
        Remove-Item -LiteralPath $Carpeta -Recurse -Force
        Escribir-Info "Listo: $zip"
    } catch {
        Escribir-Aviso "No se pudo comprimir ($($_.Exception.Message)); se deja la carpeta sin comprimir."
    }
}

# ---------------------------------------------------------------- acciones
function Respaldo-General {
    Escribir-Titulo "Respaldo general"
    $destino = Leer-Destino
    Escribir-Info "Destino actual: $destino"
    $respuesta = Read-Host "Destino (Enter para usar el actual)"
    if ($respuesta) { $destino = $respuesta.Trim() }
    if (-not (Test-Path $destino)) { New-Item -ItemType Directory -Path $destino -Force | Out-Null }
    Guardar-Destino $destino

    $carpetas = Carpetas-Usuario
    if ($carpetas.Count -eq 0) { Escribir-Error "No se encontraron carpetas de usuario."; return }
    Escribir-Info "Carpetas a respaldar:"
    foreach ($c in $carpetas) { Escribir-Info "  - $($c.Etiqueta): $($c.Ruta)" }

    $compactar = $false
    $r = Read-Host "¿Comprimir en .zip al terminar? (s/n)"
    if ($r -eq "s" -or $r -eq "S") { $compactar = $true }

    $sello = Get-Date -Format "yyyyMMdd-HHmmss"
    $carpetaRespaldo = Join-Path $destino "Respaldo_$sello"
    New-Item -ItemType Directory -Path $carpetaRespaldo -Force | Out-Null

    $fuentes = @()
    foreach ($c in $carpetas) { $fuentes += "$($c.Etiqueta)|$($c.Ruta)" }
    Escribir-Estado -Carpeta (Split-Path -Leaf $carpetaRespaldo) -Fuentes $fuentes -Copias @()

    $copias = Copiar-Arbol -Fuentes $fuentes -DestinoCarpeta $carpetaRespaldo -YaCopiados @()
    Escribir-Estado -Carpeta (Split-Path -Leaf $carpetaRespaldo) -Fuentes $fuentes -Copias $copias

    if (Test-Path $StateFile) { Remove-Item $StateFile -Force }
    Escribir-Info "Respaldo terminado en $carpetaRespaldo"
    if ($compactar) { Comprimir-Respaldo $carpetaRespaldo }
}

function Reanudar-Respaldo {
    Escribir-Titulo "Reanudar respaldo interrumpido"
    $estado = Leer-Estado
    if (-not $estado.Valido) { Escribir-Aviso "No hay ningún respaldo interrumpido."; return }

    $destino = Leer-Destino
    $carpetaRespaldo = Join-Path $destino $estado.Carpeta
    if (-not (Test-Path $carpetaRespaldo)) { Escribir-Aviso "La carpeta del respaldo ya no existe."; return }

    Escribir-Info "Respaldo: $($estado.Carpeta)"
    Escribir-Info "Archivos ya copiados: $($estado.Copias.Count)"
    $compactar = $false
    $r = Read-Host "¿Comprimir en .zip al terminar? (s/n)"
    if ($r -eq "s" -or $r -eq "S") { $compactar = $true }

    $copias = Copiar-Arbol -Fuentes $estado.Fuentes -DestinoCarpeta $carpetaRespaldo -YaCopiados $estado.Copias -Reanudando
    Escribir-Estado -Carpeta $estado.Carpeta -Fuentes $estado.Fuentes -Copias $copias
    if (Test-Path $StateFile) { Remove-Item $StateFile -Force }
    Escribir-Info "Respaldo terminado en $carpetaRespaldo"
    if ($compactar) { Comprimir-Respaldo $carpetaRespaldo }
}

function Eliminar-Respaldo {
    Escribir-Titulo "Eliminar respaldo"
    $destino = Leer-Destino
    if (-not (Test-Path $destino)) { Escribir-Aviso "No hay respaldos en $destino"; return }
    $carpetas = @(Get-ChildItem -Path $destino -Directory -ErrorAction SilentlyContinue |
                  Where-Object { $_.Name -like "Respaldo_*" } |
                  Sort-Object Name -Descending)
    if ($carpetas.Count -eq 0) { Escribir-Aviso "No hay respaldos en $destino"; return }

    Escribir-Info "Respaldos disponibles:"
    for ($i = 0; $i -lt $carpetas.Count; $i++) {
        Escribir-Info ("  {0}) {1}" -f ($i + 1), $carpetas[$i].Name)
    }
    $opcion = Read-Host "Número del respaldo a eliminar (0 para salir)"
    $numero = 0
    if (-not [int]::TryParse($opcion, [ref]$numero)) { Escribir-Aviso "Opción no válida."; return }
    if ($numero -lt 1 -or $numero -gt $carpetas.Count) { Escribir-Aviso "Opción no válida."; return }
    $objetivo = $carpetas[$numero - 1]
    Escribir-Aviso "Se va a eliminar: $($objetivo.FullName)"
    $confirmacion = Read-Host "Escribe BORRAR para confirmar"
    if ($confirmacion -ne "BORRAR") { Escribir-Info "Cancelado."; return }
    Remove-Item -LiteralPath $objetivo.FullName -Recurse -Force
    $zip = "$($objetivo.FullName).zip"
    if (Test-Path $zip) { Remove-Item -LiteralPath $zip -Force }
    Escribir-Info "Eliminado."
}

# ---------------------------------------------------------------- menu
function Menu {
    while ($true) {
        Write-Host ""
        Write-Host "  RESPALDOS.GIO - versión mínima de terminal" -ForegroundColor Green
        Write-Host "  1) Respaldo general"
        Write-Host "  2) Reanudar respaldo interrumpido"
        Write-Host "  3) Eliminar respaldo"
        Write-Host "  4) Salir"
        $opcion = Read-Host "Opción"
        switch ($opcion) {
            "1" { Respaldo-General }
            "2" { Reanudar-Respaldo }
            "3" { Eliminar-Respaldo }
            "4" { return }
            default { Escribir-Aviso "Opción no válida." }
        }
    }
}

Menu
Escribir-Info "Hasta pronto."
