# Servidor SSH + SFTP en Windows (Python + Paramiko)

Este proyecto implementa un servidor SSH en Windows con:

- Autenticación por usuario y contraseña.
- Shell interactiva de PowerShell.
- Soporte de comandos `exec` remotos.
- Subsistema SFTP compatible con WinSCP (listar, crear, renombrar, subir y borrar archivos/carpetas).
- Configuración externa por JSON para no exponer secretos en Git.

## 1. Estructura del proyecto

- `Server.py`: servidor principal SSH/SFTP.
- `requirements.txt`: dependencias de Python.
- `server_config.json`: configuración privada local (ignorada por Git).
- `server_config.example.json`: plantilla pública sin secretos.
- `.gitignore`: exclusiones para no subir datos sensibles ni entorno local.
- `host_rsa.key`: clave privada del host SSH (se autogenera si no existe).

## 2. Requisitos

- Windows 10/11.
- Python 3.10+ (recomendado).
- PowerShell (incluido en Windows).

## 3. Instalación

### 3.1 Crear y activar entorno virtual (opcional, recomendado)

Si ya tienes el entorno creado en `SServer/`, puedes usarlo. Si no:

```powershell
python -m venv SServer
SServer\Scripts\Activate.ps1
```

Si PowerShell bloquea scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
SServer\Scripts\Activate.ps1
```

### 3.2 Instalar dependencias

```powershell
pip install -r requirements.txt
```

## 4. Configuración privada (NO subir a GitHub)

### 4.1 Archivo de configuración real

Edita `server_config.json` con tus datos reales:

```json
{
  "host": "0.0.0.0",
  "port": 2222,
  "username": "TU_USUARIO",
  "password": "TU_PASSWORD_FUERTE",
  "host_key_file": "host_rsa.key",
  "sftp_root": "C:/"
}
```

### 4.2 Descripción de campos

- `host`: IP de escucha del servidor.
  - `0.0.0.0`: escucha en todas las interfaces.
  - `127.0.0.1`: solo conexiones locales.
- `port`: puerto SSH/SFTP (ej. `2222`).
- `username`: usuario permitido para autenticación.
- `password`: contraseña del usuario.
- `host_key_file`: ruta de la clave host SSH.
- `sftp_root`: raíz inicial de acceso SFTP.

### 4.3 Protección de secretos

`.gitignore` ya excluye:

- `server_config.json`
- `host_rsa.key`
- `SServer/`

Sube a GitHub solo `server_config.example.json`, nunca tu `server_config.json` real.

## 5. Ejecutar el servidor

Desde la raíz del proyecto:

```powershell
python Server.py
```

Salida esperada (aprox):

```text
[+] SSH escuchando en 0.0.0.0:2222
[+] Usuario: TU_USUARIO
[+] Ctrl+C para detener
```

## 6. Conexión por SSH (terminal)

Ejemplo desde otro equipo:

```powershell
ssh TU_USUARIO@IP_DEL_SERVIDOR -p 2222
```

En la shell remota:

- Ejecuta comandos PowerShell.
- `exit` o `quit` para salir.

## 7. Conexión por WinSCP (SFTP)

Configura WinSCP así:

- Protocolo de archivo: `SFTP`
- Nombre del servidor: `IP_DEL_SERVIDOR`
- Puerto: `2222`
- Nombre de usuario: valor de `username` en `server_config.json`
- Contraseña: valor de `password` en `server_config.json`

Ruta remota recomendada inicial:

- `/C:/`
- o `/C:/Users`

## 8. Solución de problemas

### 8.1 "Autenticación fallida" en WinSCP

Verifica:

- Que WinSCP esté usando `SFTP` (no FTP/SCP).
- Que usuario/clave en WinSCP coincidan con `server_config.json`.
- Que reiniciaste el servidor después de cambiar el JSON.

### 8.2 Error WinSCP código 4 (`Failure`) al crear carpeta

Posibles causas:

- Carpeta ya existe.
- Ruta protegida por permisos de Windows.
- Ruta inválida o fuera de alcance.

Acciones:

- Prueba en `/C:/Users` con un nombre nuevo.
- Revisa la consola del servidor: se registran errores `SFTP mkdir OSError` o `TypeError`.

### 8.3 No conecta desde otra máquina

Comprueba:

- Firewall de Windows permite el puerto configurado.
- IP y puerto correctos.
- El servidor está ejecutándose y escuchando.

## 9. Seguridad recomendada

Estado actual:

- Es un servidor funcional para uso controlado/laboratorio.
- Usa autenticación simple por password.

Mejoras recomendadas para producción:

- Usar autenticación por clave pública en vez de contraseña.
- Limitar `sftp_root` a una carpeta dedicada (no todo `C:/`).
- Ejecutar el proceso con un usuario Windows de permisos restringidos.
- Rotar contraseña y clave host periódicamente.
- Registrar auditoría de accesos y comandos.

## 10. Comandos útiles

Instalar dependencias:

```powershell
pip install -r requirements.txt
```

Ejecutar servidor:

```powershell
python Server.py
```

Detener servidor:

- `Ctrl + C` en la consola donde corre.

## 11. Notas de mantenimiento

- `server_config.json` es obligatorio: si falta, el servidor falla con error claro.
- `username` y `password` deben existir en JSON.
- Si borras `host_rsa.key`, se regenera automáticamente al iniciar.
