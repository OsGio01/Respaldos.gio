Clear-Host

# Función para pedir letra de unidad destino
function Pedir-UnidadDestino {
    while ($true) {
        $letra = Read-Host "Introduce la letra de la unidad donde quieres guardar los respaldos (ejemplo: F)"
        if ([string]::IsNullOrWhiteSpace($letra)) {
            Write-Host "No escribiste ninguna letra. Intenta de nuevo." -ForegroundColor Red
            continue
        }
        $rutaUnidad = "$letra`:\"
        if (Test-Path $rutaUnidad) {
            return $rutaUnidad
        } else {
            Write-Host "La unidad '$rutaUnidad' no existe o no esta accesible. Intenta otra." -ForegroundColor Red
        }
    }
}

# Pedimos la unidad destino para respaldos
$unidadDestino = Pedir-UnidadDestino

# Preparamos carpeta base de respaldo y log en esa unidad
$fecha = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$carpetaRespaldo = Join-Path -Path $unidadDestino -ChildPath "Respaldo_$fecha"
$log = Join-Path $carpetaRespaldo "log.txt"

# Creamos la carpeta base de respaldo
if (!(Test-Path $carpetaRespaldo)) {
    New-Item -ItemType Directory -Path $carpetaRespaldo | Out-Null
}

function Respaldo-General {
    $carpetas = @(
        "$env:USERPROFILE\Documents",
        "$env:USERPROFILE\Desktop",
        "$env:USERPROFILE\Downloads",
        "$env:USERPROFILE\Pictures",
        "$env:USERPROFILE\Music",
        "$env:USERPROFILE\Videos",
        "$env:USERPROFILE\Escritorio",
        "$env:USERPROFILE\Descargas",
        "$env:USERPROFILE\Documentos",
        "$env:USERPROFILE\Imágenes",
        "$env:USERPROFILE\Música",
        "$env:USERPROFILE\Videos"


    )
    foreach ($carpeta in $carpetas) {
        if (Test-Path $carpeta) {
            $destino = Join-Path $carpetaRespaldo (Split-Path $carpeta -Leaf)
            try {
            Copy-Item -Path $carpeta -Destination $destino -Recurse -Force -ErrorAction Stop
            Add-Content -Path $log -Value "Respaldo exitoso de $carpeta"
        } catch {
            Add-Content -Path $log -Value ("Error al respaldar " + $carpeta + ": " + $_.Exception.Message)
        }
        }
    }
}

function Respaldo-Extensiones {
    $extensiones = @("*.pdf", "*.docx", "*.xlsx", "*.pptx", "*.txt", "*.jpg", "*.png", "*.mp4", "*.mp3", "*.zip", "*.rar")
    foreach ($ext in $extensiones) {
        $archivos = Get-ChildItem -Path $env:USERPROFILE -Recurse -Include $ext -ErrorAction SilentlyContinue
        foreach ($archivo in $archivos) {
            $tipo = $archivo.Extension.TrimStart('.')
            $destinoTipo = Join-Path $carpetaRespaldo $tipo
            if (!(Test-Path $destinoTipo)) {
                New-Item -ItemType Directory -Path $destinoTipo -Force | Out-Null
            }
            try {
                Copy-Item -Path $archivo.FullName -Destination $destinoTipo -Force -ErrorAction Stop
                Add-Content -Path $log -Value "Copiado: $($archivo.FullName)"
            } catch {
                Add-Content -Path $log -Value "Error copiando $($archivo.FullName): $($_.Exception.Message)"
            }
        }
    }
    Write-Host "Respaldo por extensiones finalizado."
}

function Respaldo-Unidades {
    $unidades = Get-PSDrive -PSProvider FileSystem | Where-Object {
        ($_.Root -ne $env:SystemDrive + "\") -and
        ($_.Free -gt 0) -and
        ($_.Used -gt 0)
    }

    if ($unidades.Count -eq 0) {
        Write-Host "No se detectaron unidades externas o adicionales."
        return
    }

    Write-Host "Unidades detectadas:"
    $i = 1
    foreach ($unidad in $unidades) {
        Write-Host "$i) $($unidad.Name): $($unidad.Root)"
        $i++
    }

    $eleccion = Read-Host "Selecciona el numero de la unidad que deseas respaldar"
    $indice = [int]$eleccion - 1
    if ($indice -ge 0 -and $indice -lt $unidades.Count) {
        $unidad = $unidades[$indice]
        $destinoUnidad = Join-Path $carpetaRespaldo "Unidad_$($unidad.Name)"
        try {
            Copy-Item -Path $unidad.Root -Destination $destinoUnidad -Recurse -Force -ErrorAction Stop
            Add-Content -Path $log -Value "Respaldo completo de unidad $($unidad.Name)"
            Write-Host "Respaldo completo de unidad $($unidad.Name)"
        } catch {
            Add-Content -Path $log -Value "Error respaldando unidad $($unidad.Name): $($_.Exception.Message)"
            Write-Host "Error respaldando unidad $($unidad.Name)" -ForegroundColor Red
        }
    } else {
        Write-Host "Selección no válida."
    }
}

function Respaldo-XAMPP {
    $ruta = "C:\xampp\htdocs"
    if (Test-Path $ruta) {
        $destino = Join-Path $carpetaRespaldo "htdocs"
        try {
            Copy-Item -Path $ruta -Destination $destino -Recurse -Force -ErrorAction Stop
            Add-Content -Path $log -Value "Respaldo exitoso de C:\xampp\htdocs"
            Write-Host "Respaldo exitoso de C:\xampp\htdocs"
        } catch {
            Add-Content -Path $log -Value "Error al respaldar C:\xampp\htdocs: $($_.Exception.Message)"
            Write-Host "Error al respaldar C:\xampp\htdocs" -ForegroundColor Red
        }
    } else {
        Add-Content -Path $log -Value "La ruta C:\xampp\htdocs no existe."
        Write-Host "La ruta C:\xampp\htdocs no existe." -ForegroundColor Yellow
    }
}

function Eliminar-Respaldos {
    $respaldos = Get-ChildItem -Path $unidadDestino -Directory | Where-Object { $_.Name -like "Respaldo_*" }
    if ($respaldos.Count -eq 0) {
        Write-Host "No hay respaldos anteriores para eliminar."
        return
    }
    Write-Host "Respaldos encontrados:"
    $i = 1
    foreach ($respaldo in $respaldos) {
        Write-Host "$i) $($respaldo.Name)"
        $i++
    }
    $eleccion = Read-Host "Selecciona el numero del respaldo a eliminar o escribe 'todos' para eliminar todos"
    if ($eleccion -eq "todos") {
        foreach ($respaldo in $respaldos) {
            Remove-Item -Path $respaldo.FullName -Recurse -Force
        }
        Write-Host "Todos los respaldos han sido eliminados."
    } elseif ($eleccion -match '^\d+$') {
        $indice = [int]$eleccion - 1
        if ($indice -ge 0 -and $indice -lt $respaldos.Count) {
            Remove-Item -Path $respaldos[$indice].FullName -Recurse -Force
            Write-Host "Respaldo eliminado: $($respaldos[$indice].Name)"
        } else {
            Write-Host "Selección no válida."
        }
    } else {
        Write-Host "Entrada no válida."
    }
}

function Mostrar-Menu {
    Clear-Host
    Write-Host "====================================" -ForegroundColor Cyan
    Write-Host "         Menu Respaldos" -ForegroundColor Yellow
    Write-Host "====================================" -ForegroundColor Cyan
    Write-Host "1) Respaldo general (Documentos, Escritorio, Descargas, Imagenes)"
    Write-Host "2) Respaldo por tipo de extension (Archivos organizados en carpetas)"
    Write-Host "3) Respaldo de unidad extraible o disco (USB, disco duro, CD, disquete)"
    Write-Host "4) Respaldo solo carpeta C:\xampp\htdocs"
    Write-Host "5) Eliminar respaldos anteriores"
    Write-Host "6) Salir"
}

do {
    Mostrar-Menu
    $opcion = Read-Host "Selecciona una opcion"
    switch ($opcion) {
        "1" { Respaldo-General }
        "2" { Respaldo-Extensiones }
        "3" { Respaldo-Unidades }
        "4" { Respaldo-XAMPP }
        "5" { Eliminar-Respaldos }
        "6" { Write-Host "Saliendo..."; exit}
        default { Write-Host "Opcion no valida" }
    }
    if ($opcion -ne "6") {
        Pause
    }
} while ($true)
