# Diagramas de arquitectura

Fuente reproducible de los 14 diagramas del paquete documental.

| Archivo | Contenido |
|---|---|
| `engine.py` | Motor mínimo sin dependencias: nodos, agrupaciones y conexiones → SVG autocontenido (logos en base64) → PNG con Chrome/Edge headless |
| `build_diagrams.py` | Especificación de cada diagrama |
| `NN_*.svg` | Fuente vectorial generada (se puede abrir en el navegador o incrustar) |

Las exportaciones PNG (2×) están en [`../imagenes/`](../imagenes/) y los logos oficiales en [`../imagenes/logos/`](../imagenes/logos/) (ver su README de licencias).

```powershell
python docs/diagramas/build_diagrams.py                 # todos
python docs/diagramas/build_diagrams.py 08_multiagentes # uno
```

Si Chrome o Edge no están en la ruta estándar, defina `CHROME_PATH`. Convenciones: línea discontinua = opcional, deshabilitado o con defecto conocido; colores de flecha por capa (verde datos, naranja ML, morado agentes, azul Azure, magenta seguridad).

| # | Diagrama | Documento |
|---|---|---|
| 01 | Estructura del repositorio | [01](../01_Estructura_Repositorio.md) |
| 02 | Arquitectura general | [02](../02_Arquitectura_General.md) |
| 03 | Frontend | [06](../06_Arquitectura_Frontend.md) |
| 04 | Backend | [07](../07_Arquitectura_Backend.md) |
| 05 | Base de datos | [08](../08_Arquitectura_BD.md) |
| 06 | Azure | [09](../09_Arquitectura_Azure.md) |
| 07 | Pipeline ML | [04](../04_Arquitectura_ML.md) |
| 08 | Multiagentes | [05](../05_Arquitectura_MultiAgente.md) |
| 09 | Flujo de entrenamiento | [04](../04_Arquitectura_ML.md) |
| 10 | Flujo de inferencia | [04](../04_Arquitectura_ML.md) |
| 11 | Flujo de datos | [03](../03_Arquitectura_Datos.md) |
| 12 | CI/CD | [11](../11_DevOps_CICD.md) |
| 13 | Seguridad | [10](../10_Seguridad_Gobierno.md) |
| 14 | Arquitectura E2E | [00](../00_Resumen_Ejecutivo.md), [02](../02_Arquitectura_General.md) |
