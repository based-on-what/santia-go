# 🚀 Deployment a Railway

**SantiaGO** está listo para deployar 100% en **Railway.app** (frontend + backend Python).

## ¿Por qué Railway?

✅ Python nativo (sin conversiones)  
✅ Tiempo de ejecución ilimitado  
✅ Archivos estáticos servidos automáticamente  
✅ Gratuito (hasta $5 USD/mes)  
✅ 0 configuración adicional  

## Paso 1: Preparar el Repo

```bash
# Asegúrate de que tienes todo commiteado
git add .
git commit -m "Preparado para Railway deployment"
```

## Paso 2: Conectar con Railway

### Opción A: Desde la CLI (Recomendado)

```bash
# 1. Instalar Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Crear proyecto en Railway
railway init

# ✅ Selecciona: "Create a new project"
# ✅ Dame un nombre: santia-go (o el que prefieras)

# 4. Conectar repo
railway link

# 5. Deploy
railway up
```

### Opción B: Desde el sitio web

1. Ve a [railway.app](https://railway.app)
2. Click en "New Project"
3. Select "Deploy from GitHub"
4. Conecta tu repo de GitHub
5. Selecciona la rama `main`
6. ✅ Railway detectará automáticamente `Procfile` y `requirements.txt`

## Paso 3: Verificar que Funciona

```bash
# Ver logs en tiempo real
railway logs

# Ver URL deplorada
railway status
```

**Output esperado:**
```
✓ Your application is live at: https://santia-go-production.up.railway.app
```

## URLs del Backend

```
GET /                           → Raíz (doc)
GET /api/paradero/{id}         → Datos del paradero
GET /api/metro/estacion        → Datos de estación metro
```

**Ejemplo:**
```bash
curl https://santia-go-production.up.railway.app/paradero/PA443
curl https://santia-go-production.up.railway.app/metro/estacion?nombre=Baquedano
```

## URLs del Frontend

```
https://santia-go-production.up.railway.app/          → HTML principal
https://santia-go-production.up.railway.app/js/main.js → JavaScript
https://santia-go-production.up.railway.app/css/main.css → Estilos
```

## Structure Esperada

```
santiaGO/
├── Procfile              ← Railway lo usa
├── README.railway.md     ← Este archivo
├── public/               ← Frontend (HTML/CSS/JS)
│   ├── index.html
│   ├── css/main.css
│   ├── js/main.js
│   └── data/...
└── tools/
    └── python/
        ├── api.py        ← Backend FastAPI
        ├── requirements.txt
        ├── metro/
        └── ...
```

## Troubleshooting

### ❌ Error: "Static files not found"

Verifica que la estructura sea correcta:

```bash
# Debería mostrar los archivos
ls -la public/index.html
ls -la public/css/main.css
ls -la public/js/main.js
```

**Solución:** Si falta alguno, agregalo a `public/`

### ❌ Error: "módulo metro no encontrado"

Railway está ejecutando desde la raíz del proyecto. Verifica:

```bash
ls -la tools/python/metro/
ls -la tools/python/metro/__init__.py
```

**Solución:** El `__init__.py` debe existir en la carpeta metro

### ❌ Error 502 en paraderos

Significa que iBUS está rechazando la conexión desde Railway IPs.

**Soluciones:**
1. Esperar (iBUS puede estar congestionado)
2. Usar VPN/proxy (Railway soporta eso)
3. Usar API alternativa si existe

### ❌ Cambios locales no se ven

Railway solo deploya cuando haces push:

```bash
git push origin main
```

Espera 2-3 minutos para que Railway recompile y despliegue.

## Variables de Entorno (Opcional)

Si necesitas secrets/variables:

```bash
railway env
# Agrega variables como:
# VARIABLE_NAME=valor
```

## Costo

- **Gratuito:** Cada cuenta de Railway tiene $5 USD gratis por mes
- **Uso típico:** ~$2-3 USD/mes
- **Si se pasa:** Solo pagas lo extra

## Monitoreo

Railway tiene dashboard con:
- 📊 CPU/Memoria
- 📝 Logs en vivo
- 🔄 Restart automático si falla
- 📈 Estadísticas de uso

Accede a [railway.app/dashboard](https://railway.app/dashboard)

## Actualizar Deployado

Simplemente haz push a main:

```bash
git add .
git commit -m "Cambios importantes"
git push origin main
```

Railway detectará cambios y redesplegará automáticamente.

---

**¿Preguntas?** Consulta la [docs de Railway](https://docs.railway.app/)
