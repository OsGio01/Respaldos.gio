#!/usr/bin/env python3
"""Entry principal del programa Respaldos.Gio (v6.2)."""
import os

from core import constantes, configuracion, estados, motor
from fronts.hud import FronteHUD


if __name__ == "__main__":
    config = configuracion.Configuracion.cargar()
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = constantes.RUTA_RESPALDOS
        config.guardar()
    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(config, gestor)
    hud = FronteHUD(config, gestor, motor_obj)
    hud.ejecutar()
