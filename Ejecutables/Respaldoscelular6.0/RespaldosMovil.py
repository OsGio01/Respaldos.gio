#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Respaldos.Gio - front movil (v6.0).

Delega en el front movil del nucleo OOP (misma cara que el HUD minimalista).
"""
from core import configuracion, estados, motor
from fronts.movil import FronteMovil


def iniciar_movil() -> None:
    config = configuracion.Configuracion.cargar()
    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(config, gestor)
    FronteMovil(config, gestor, motor_obj)


if __name__ == "__main__":
    iniciar_movil()
