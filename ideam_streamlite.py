import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from colombia_hydrodata import Client
from shapely.geometry import Point
import requests
from io import StringIO
from datetime import datetime
import folium
from streamlit_folium import folium_static

# ===================================================================
# FUNCIONES AUXILIARES (con caché)
# ===================================================================

@st.cache_data(ttl=3600)
def get_stations_nearby(lat, lon, n=5):
    """Obtiene las n estaciones más cercanas."""
    cliente = Client()
    catalogo = cliente.catalog
    mi_ubicacion = Point(lon, lat)
    catalogo['distancia'] = catalogo.geometry.distance(mi_ubicacion)
    estaciones = catalogo.sort_values('distancia').head(n)
    return estaciones[['name', 'id', 'department', 'municipality', 'distancia', 'geometry']]

@st.cache_data(ttl=600)
def descargar_datos_ideam(codigo, dataset_id):
    """Descarga datos diarios desde datos.gov.co."""
    base_url = f"https://www.datos.gov.co/resource/{dataset_id}.csv"
    params = {"codigoestacion": codigo, "$limit": 100000}
    try:
        response = requests.get(base_url, params=params, timeout=30)
        if response.status_code != 200:
            return None
        df = pd.read_csv(StringIO(response.text))
        if df.empty:
            return None
        
        # Estandarización de columnas
        if 'fechaobservacion' in df.columns:
            df['fecha'] = pd.to_datetime(df['fechaobservacion'])
        elif 'fecha' in df.columns:
            df['fecha'] = pd.to_datetime(df['fecha'])
        else:
            return None
        
        if 'valorobservado' in df.columns:
            df.rename(columns={'valorobservado': 'valor'}, inplace=True)
        df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
        df = df.dropna(subset=['valor', 'fecha'])
        if df.empty:
            return None
        
        # Agrupar por día
        df['fecha_dia'] = df['fecha'].dt.date
        df_diario = df.groupby('fecha_dia')['valor'].mean().reset_index()
        df_diario['fecha'] = pd.to_datetime(df_diario['fecha_dia'])
        return df_diario[['fecha', 'valor']].sort_values('fecha')
    except Exception:
        return None

# ===================================================================
# CONFIGURACIÓN DE LA PÁGINA
# ===================================================================
st.set_page_config(page_title="Visor Climático IDEAM", page_icon="🌦️", layout="wide")
st.title("🌦️ Visor de Datos Climáticos - IDEAM")
st.markdown("Explora datos históricos de **precipitación y temperatura** de estaciones IDEAM en Colombia.")

# Inicializar session_state si no existe
if "estaciones" not in st.session_state:
    st.session_state.estaciones = None
if "seleccion" not in st.session_state:
    st.session_state.seleccion = None
if "codigo" not in st.session_state:
    st.session_state.codigo = None
if "nombre" not in st.session_state:
    st.session_state.nombre = None
if "datos" not in st.session_state:
    st.session_state.datos = None
if "variables" not in st.session_state:
    st.session_state.variables = None
if "fecha_ini" not in st.session_state:
    st.session_state.fecha_ini = datetime(1970, 1, 1)
if "fecha_fin" not in st.session_state:
    st.session_state.fecha_fin = datetime.now()

# ===================================================================
# SIDEBAR: BÚSQUEDA DE ESTACIONES
# ===================================================================
with st.sidebar:
    st.header("📍 Ubicación")
    lat = st.number_input("Latitud", value=4.7110, format="%.4f", step=0.001)
    lon = st.number_input("Longitud", value=-74.0721, format="%.4f", step=0.001)
    n_estaciones = st.slider("Número de estaciones cercanas", 1, 10, 5)
    buscar = st.button("🔍 Buscar estaciones", type="primary")

# ===================================================================
# LÓGICA DE BÚSQUEDA (se ejecuta solo cuando se presiona el botón)
# ===================================================================
if buscar:
    with st.spinner("Conectando al IDEAM..."):
        try:
            estaciones = get_stations_nearby(lat, lon, n_estaciones)
            if estaciones.empty:
                st.error("No se encontraron estaciones cercanas.")
                st.session_state.estaciones = None
                st.stop()
            # Guardar en session_state
            st.session_state.estaciones = estaciones
            # Seleccionar la primera automáticamente
            primera = estaciones.iloc[0]
            st.session_state.seleccion = f"{primera['name']} ({primera['id']})"
            st.session_state.codigo = primera['id']
            st.session_state.nombre = primera['name']
            # Limpiar datos anteriores
            st.session_state.datos = None
        except Exception as e:
            st.error(f"Error: {e}")
            st.session_state.estaciones = None
            st.stop()

# ===================================================================
# CUERPO PRINCIPAL: Mostrar si hay estaciones en session_state
# ===================================================================
if st.session_state.estaciones is not None:
    estaciones = st.session_state.estaciones
    
    # Mostrar tabla
    st.subheader("📌 Estaciones más cercanas")
    st.dataframe(
        estaciones[['name', 'id', 'department', 'municipality']].rename(
            columns={'name': 'Nombre', 'id': 'Código', 'department': 'Departamento', 'municipality': 'Municipio'}
        ),
        use_container_width=True
    )
    
    # Mapa
    st.subheader("🗺️ Mapa de estaciones")
    m = folium.Map(location=[lat, lon], zoom_start=12)
    folium.Marker([lat, lon], popup="Tu ubicación", icon=folium.Icon(color="red")).add_to(m)
    for _, row in estaciones.iterrows():
        folium.Marker(
            [row.geometry.y, row.geometry.x],
            popup=f"{row['name']} ({row['id']})",
            icon=folium.Icon(color="blue", icon="cloud")
        ).add_to(m)
    folium_static(m, width=700, height=400)
    
    # Selección de estación (con un key que actualiza session_state)
    opciones = {f"{row['name']} ({row['id']})": row['id'] for _, row in estaciones.iterrows()}
    nueva_seleccion = st.selectbox(
        "Selecciona una estación",
        list(opciones.keys()),
        index=list(opciones.keys()).index(st.session_state.seleccion) if st.session_state.seleccion in opciones else 0,
        key="select_estacion"
    )
    # Si cambió la selección, actualizar session_state y limpiar datos
    if nueva_seleccion != st.session_state.seleccion:
        st.session_state.seleccion = nueva_seleccion
        st.session_state.codigo = opciones[nueva_seleccion]
        st.session_state.nombre = nueva_seleccion.split(" (")[0]
        st.session_state.datos = None  # Limpiar datos al cambiar de estación
    
    # Variables (multiselect)
    variables = st.multiselect(
        "Variables a descargar",
        options=["Precipitación", "Temperatura"],
        default=["Precipitación"] if st.session_state.variables is None else st.session_state.variables,
        key="select_variables"
    )
    st.session_state.variables = variables  # Guardar estado
    
    # Rango de fechas
    col1, col2 = st.columns(2)
    with col1:
        fecha_ini = st.date_input(
            "Fecha inicial",
            st.session_state.fecha_ini,
            min_value=datetime(1950, 1, 1),
            max_value=datetime.now(),
            key="fecha_ini_input"
        )
    with col2:
        fecha_fin = st.date_input(
            "Fecha final",
            st.session_state.fecha_fin,
            min_value=datetime(1950, 1, 1),
            max_value=datetime.now(),
            key="fecha_fin_input"
        )
    st.session_state.fecha_ini = fecha_ini
    st.session_state.fecha_fin = fecha_fin
    
    # Botón para descargar/graficar
    if st.button("📥 Descargar y graficar", type="primary"):
        datasets = {"Precipitación": "s54a-sgyg", "Temperatura": "sbwg-7ju4"}
        datos = {}
        
        with st.spinner("Descargando datos..."):
            for var in variables:
                df = descargar_datos_ideam(st.session_state.codigo, datasets[var])
                if df is not None:
                    df = df[(df['fecha'] >= pd.to_datetime(fecha_ini)) & 
                            (df['fecha'] <= pd.to_datetime(fecha_fin))]
                    if not df.empty:
                        datos[var] = df
                    else:
                        st.warning(f"No hay datos de {var} en el rango seleccionado.")
                else:
                    st.warning(f"No se pudieron obtener datos de {var}.")
        
        if datos:
            st.session_state.datos = datos
        else:
            st.error("No se descargaron datos.")
            st.session_state.datos = None
    
    # ===================================================================
    # MOSTRAR DATOS SI EXISTEN EN SESSION_STATE
    # ===================================================================
    if st.session_state.datos is not None:
        datos = st.session_state.datos
        st.subheader(f"📈 Datos de {st.session_state.nombre}")
        
        tabs = st.tabs(list(datos.keys()))
        for idx, (var, df) in enumerate(datos.items()):
            with tabs[idx]:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Promedio", f"{df['valor'].mean():.2f}")
                col2.metric("Máximo", f"{df['valor'].max():.2f}")
                col3.metric("Mínimo", f"{df['valor'].min():.2f}")
                col4.metric("Días", len(df))
                
                if var == "Precipitación":
                    # Días secos consecutivos
                    df['seco'] = df['valor'] < 1
                    racha_max = 0
                    racha_act = 0
                    for seco in df['seco']:
                        if seco:
                            racha_act += 1
                            if racha_act > racha_max:
                                racha_max = racha_act
                        else:
                            racha_act = 0
                    st.metric("Máxima racha de días secos", f"{racha_max} días")
                
                fig, ax = plt.subplots(figsize=(12, 5))
                color = 'blue' if var == "Precipitación" else 'red'
                ax.plot(df['fecha'], df['valor'], color=color, linewidth=1)
                ax.set_title(f"{var} - {st.session_state.nombre}")
                ax.set_xlabel("Fecha")
                ax.set_ylabel("mm" if var == "Precipitación" else "°C")
                ax.grid(True, linestyle='--', alpha=0.6)
                st.pyplot(fig)
                
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📄 Descargar {var} (CSV)",
                    data=csv,
                    file_name=f"{st.session_state.nombre}_{var}_{fecha_ini}_{fecha_fin}.csv",
                    mime='text/csv'
                )
else:
    st.info("🔍 Ingresa coordenadas y presiona 'Buscar estaciones'.")
    st.map(pd.DataFrame({'lat': [4.7110], 'lon': [-74.0721]}))

st.markdown("---")
st.caption("Datos: IDEAM a través de datos.gov.co | App con Streamlit")
    # Mostrar mapa de Colombia con ubicación por defecto
    st.map(pd.DataFrame({'lat': [4.7110], 'lon': [-74.0721]}))

# ===================================================================
# PIE DE PÁGINA
# ===================================================================
st.markdown("---")
st.caption("Datos proporcionados por el IDEAM a través de datos.gov.co. Aplicación creada con Streamlit.")
