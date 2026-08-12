# Tarea 1: Arquitectura de Software

**Nombre:** Sergio Rojas Gutiérrez

**Rol:** 202273619-4

## Video

[Link a YouTube](https://youtu.be/xWacTz_hP0c)

## Instrucciones de Ejecución

1. **Instalar el plugin de Loki para Docker**: Si aún no tienes el driver de logging de Loki instalado en tu máquina, es necesario ejecutar el siguiente comando en tu terminal antes de levantar los servicios:
   ```bash
   docker plugin install grafana/loki-docker-driver:latest --alias loki --grant-all-permissions

2. **Levantar los servicios**: Utiliza el comando integrado para construir y levantar todos los contenedores en segundo plano:
    ```bash
   make up
    ```
   Nota: Al finalizar la ejecución del comando, podrás verificar en tu aplicación de Docker (ej. Docker Desktop) que todos los servicios se levantaron correctamente.
3. **Poblar las bases de datos**: Para generar los datos iniciales y el tráfico necesario para tener logs, ejecuta:
    ```bash
   make seed
    ```

## Configuración de Grafana
Una vez que todo esté en ejecución, sigue estos pasos para configurar la visualización:

1. Abre tu navegador y accede a http://localhost:3000.

2. En el menú lateral izquierdo, dirígete a Connections > Data sources.

3. Haz clic en Add data source y selecciona Loki.

4. En el campo de conexión (URL), ingresa exactamente lo siguiente:
    ```
    http://loki:3100
    ```
    
    (Se utiliza esta ruta en lugar de localhost porque Grafana y Loki se están comunicando a través de la red interna de Docker).

5. Haz scroll hasta el fondo y presiona el botón Save & test. Debería aparecer una notificación verde indicando éxito.

## Uso y Consultas LogQL
Para probar el sistema, dirígete a la pestaña Explore (ícono de brújula en el menú lateral). Cambia la vista de "Builder" a "Code" a la derecha de la barra de búsqueda para poder ingresar las consultas.

1. Aislar los logs de un contenedor específico:
    ```python
    {container="demo_01-demo_01_service_02-1"}
    ```

    Con esta consulta filtras toda la información para ver exclusivamente la actividad de un contenedor.

2. Detectar el problema de latencia n+1: Para recrear el error de forma deliberada, ejecuta el siguiente comando en tu terminal:
    ```bash
    curl "http://localhost:5001/teams?expand=players"
    ```

Espera a que termine (tomará unos segundos) y luego ejecuta esta consulta en Grafana para aislar directamente la advertencia:

```
    {container="demo_01-demo_01_service_02-1"} |= "n+1"
```
Esta técnica permite encontrar rápidamente el warning y es aplicable a distintos escenarios operativos con diferentes mensajes de error.

## Declaración de uso de IA
Tal como se menciona en la demostración en video, declaro haber utilizado IA generativa (Gemini) como herramienta de apoyo en la configuración de la infraestructura y para la depuración de errores durante el desarrollo.

Para mayor transparencia acerca del proceso iterativo y las resoluciones, adjunto el enlace a la conversación completa:

[Conversación Completa Gemini](https://share.gemini.google/hxBniSGo0kMY)