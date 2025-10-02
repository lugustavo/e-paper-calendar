#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar recursos do sistema e file descriptors
�til para diagnosticar vazamentos de recursos
"""

import os
import sys
import psutil
from pathlib import Path

def check_file_descriptors():
    """Verifica file descriptors abertos pelo processo atual"""
    try:
        pid = os.getpid()
        process = psutil.Process(pid)
        
        # Pega lista de arquivos abertos
        open_files = process.open_files()
        connections = process.connections()
        
        print(f"\n{'='*60}")
        print(f"FILE DESCRIPTORS - PID {pid}")
        print(f"{'='*60}")
        print(f"Arquivos abertos: {len(open_files)}")
        print(f"Conex�es de rede: {len(connections)}")
        print(f"Total FDs: {process.num_fds()}")
        
        # Limites do sistema
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        print(f"\nLimites do sistema:")
        print(f"  Soft limit: {soft}")
        print(f"  Hard limit: {hard}")
        print(f"  Uso atual: {process.num_fds()}/{soft} ({process.num_fds()*100/soft:.1f}%)")
        
        # Lista arquivos abertos (primeiros 20)
        if open_files:
            print(f"\nArquivos abertos (primeiros 20):")
            for f in open_files[:20]:
                print(f"  - {f.path} (fd={f.fd})")
            if len(open_files) > 20:
                print(f"  ... e mais {len(open_files)-20} arquivos")
        
        # Verifica dispositivos SPI
        spi_devices = [f for f in open_files if 'spi' in f.path.lower()]
        if spi_devices:
            print(f"\n??  ATEN��O: {len(spi_devices)} dispositivos SPI abertos:")
            for f in spi_devices:
                print(f"  - {f.path} (fd={f.fd})")
        
        # Mem�ria
        mem_info = process.memory_info()
        print(f"\nMem�ria:")
        print(f"  RSS: {mem_info.rss / 1024 / 1024:.1f} MB")
        print(f"  VMS: {mem_info.vms / 1024 / 1024:.1f} MB")
        
        # Threads
        print(f"\nThreads: {process.num_threads()}")
        
        return True
        
    except Exception as e:
        print(f"Erro ao verificar file descriptors: {e}")
        return False

def check_system_resources():
    """Verifica recursos gerais do sistema"""
    print(f"\n{'='*60}")
    print(f"RECURSOS DO SISTEMA")
    print(f"{'='*60}")
    
    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    print(f"CPU: {cpu_percent}%")
    
    # Mem�ria
    mem = psutil.virtual_memory()
    print(f"Mem�ria: {mem.percent}% usado ({mem.used/1024/1024:.0f}/{mem.total/1024/1024:.0f} MB)")
    
    # Disco
    disk = psutil.disk_usage('/')
    print(f"Disco /: {disk.percent}% usado ({disk.used/1024/1024/1024:.1f}/{disk.total/1024/1024/1024:.1f} GB)")
    
    # Temperature (Raspberry Pi espec�fico)
    try:
        temp_path = Path('/sys/class/thermal/thermal_zone0/temp')
        if temp_path.exists():
            temp = int(temp_path.read_text()) / 1000
            print(f"Temperatura: {temp:.1f}�C")
    except:
        pass

def monitor_process(pid=None, interval=5):
    """Monitora processo continuamente"""
    import time
    
    if pid is None:
        pid = os.getpid()
    
    try:
        process = psutil.Process(pid)
        print(f"\nMonitorando processo {pid} - Ctrl+C para parar")
        print(f"{'Tempo':<10} {'FDs':<8} {'Mem(MB)':<10} {'CPU%':<8}")
        print("-" * 40)
        
        start_time = time.time()
        while True:
            elapsed = int(time.time() - start_time)
            fds = process.num_fds()
            mem = process.memory_info().rss / 1024 / 1024
            cpu = process.cpu_percent(interval=0.1)
            
            print(f"{elapsed:<10} {fds:<8} {mem:<10.1f} {cpu:<8.1f}")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\nMonitoramento interrompido")
    except Exception as e:
        print(f"Erro no monitoramento: {e}")

def find_epaper_process():
    """Encontra processo do e-paper calendar"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and any('main.py' in cmd for cmd in cmdline):
                return proc.info['pid']
        except:
            pass
    return None

def main():
    print("?? VERIFICADOR DE RECURSOS DO SISTEMA")
    
    import argparse
    parser = argparse.ArgumentParser(description='Verifica recursos do sistema e file descriptors')
    parser.add_argument('--monitor', action='store_true', help='Monitora continuamente')
    parser.add_argument('--pid', type=int, help='PID do processo a monitorar')
    parser.add_argument('--interval', type=int, default=5, help='Intervalo de monitoramento (segundos)')
    args = parser.parse_args()
    
    if args.monitor:
        pid = args.pid
        if pid is None:
            # Tenta encontrar processo do e-paper
            pid = find_epaper_process()
            if pid:
                print(f"Encontrado processo e-paper: PID {pid}")
            else:
                print("Processo e-paper n�o encontrado, monitorando processo atual")
                pid = os.getpid()
        
        monitor_process(pid, args.interval)
    else:
        # Verifica��o �nica
        check_system_resources()
        check_file_descriptors()
        
        # Verifica processo e-paper se estiver rodando
        epaper_pid = find_epaper_process()
        if epaper_pid and epaper_pid != os.getpid():
            print(f"\n{'='*60}")
            print(f"PROCESSO E-PAPER CALENDAR (PID {epaper_pid})")
            print(f"{'='*60}")
            try:
                proc = psutil.Process(epaper_pid)
                print(f"FDs abertos: {proc.num_fds()}")
                print(f"Mem�ria: {proc.memory_info().rss / 1024 / 1024:.1f} MB")
                print(f"CPU: {proc.cpu_percent()}%")
                print(f"\nUse --monitor --pid {epaper_pid} para monitorar continuamente")
            except Exception as e:
                print(f"Erro ao acessar processo: {e}")

if __name__ == "__main__":
    main()