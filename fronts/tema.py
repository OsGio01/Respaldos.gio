#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Design system del front de escritorio (Respaldos.Gio v6.0).

Tokens de color y medidas compartidos por el HUD, los paneles y el front
movil. Toda la logica de negocio vive en `core`; aqui solo hay presentacion.
"""

# --- base -----------------------------------------------------------------
COLOR_FONDO = "#0a0e1a"        # fondo principal
COLOR_PANEL = "#111830"        # paneles y tarjetas
COLOR_PANEL_2 = "#0d1428"      # fondos alternos (log, campos)
COLOR_BORDE = "#1e2a52"        # bordes y lineas divisorias
COLOR_TEXTO = "#e2e8f0"        # texto principal
COLOR_SUBTEXTO = "#64748b"     # texto secundario

# --- acento (indigo -> cyan) ---------------------------------------------
COLOR_ACCENTO = "#6366f1"
COLOR_ACCENTO_FIN = "#22d3ee"
COLOR_ACCENTO_SOMBRA = "#312e81"

# --- log ------------------------------------------------------------------
COLOR_LOG_INFO = "#94a3b8"
COLOR_LOG_OK = "#22c55e"
COLOR_LOG_WARN = "#f59e0b"
COLOR_LOG_ERROR = "#ef4444"
COLOR_LOG_ACCION = "#818cf8"

# --- estados --------------------------------------------------------------
COLOR_ESTADO_IDLE = "#64748b"
COLOR_ESTADO_OK = "#22c55e"
COLOR_ESTADO_WARN = "#f59e0b"
COLOR_ESTADO_ERROR = "#ef4444"
COLOR_ESTADO_RUNNING = "#818cf8"

# --- barra lateral --------------------------------------------------------
COLOR_SIDEBAR = "#0c1226"
COLOR_SIDEBAR_ACTIVO = "#16213f"
COLOR_SIDEBAR_HOVER = "#131b33"

# --- anillo de progreso ---------------------------------------------------
ANCHO_ARCO = 220
MARGEN_ARCO = 16
COLOR_ARCO = "#6366f1"
COLOR_ARCO_OK = "#22c55e"

# --- medidas --------------------------------------------------------------
ANCHO_SIDEBAR = 236
ANCHO_VENTANA = 1180
ALTO_VENTANA = 900
ALTO_LOG = 150

# --- medidas de los paneles ----------------------------------------------
# El front de escritorio usa los valores por defecto; el front movil los
# reduce antes de construir los paneles para que quepan en su ventana.
ANCHO_TEXTO = 700      # wraplength de los textos largos (px)
LARGO_ESCALA = 320     # longitud de los sliders (px)
ES_ANCHO = True        # False cuando el front es estrecho (celular)
