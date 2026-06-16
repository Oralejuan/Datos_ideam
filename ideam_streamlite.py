import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from colombia_hydrodata import Client
from shapely.geometry import Point
import requests
from io import StringIO
from datetime import datetime, timedelta

# ===================================================================
# FUNCIONES AUXILIARES
# ===================================================================

@st.cache_data(ttl=3600)
def get_stations_nearby(lat, lon, n=5):
    """
    Obtiene las n estaciones más cercanas a las coordenadas dadas.
    Usa caché para no recargar el catálogo cada vez.
    """
    cliente = Client()
    catalogo = cliente.catalog
    mi_ubicacion = Point(lon, lat)
    catalogo['distancia'] = catalogo.geometry.distance(mi_ubicacion)
    estaciones = catalogo.sort_values('distancia').head(n)
    return estaciones[['name', 'id', 'department', 'municipality', 'distancia']]

@st.cache_data(ttl=600)
def descargar_datos_ideam(codigo, dataset_id):
    """
    Descarga datos de un dataset de datos.gov.co para una estación específica.
    Retorna un DataFrame con columnas 'fecha' y 'valor' (promedio diario).
    """
    base_url = f"https://www.datos.gov.co/resource/{dataset_id}.csv"
    params = {
        "codigoestacion": codigo,
        "$limit": 100000
    }
    try:
        response = requests.get(base_url, params=params, timeout=30)
        if response.status_code != 200:
            st.warning(f"Error {response.status_code} al descargar dataset {dataset_id}")
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
            st.warning(f"No se encontró columna de fecha en {dataset_id}")
            return None
        
        if 'valorobservado' in df.columns:
            df.rename(columns={'valorobservado': 'valor'}, inplace=True)
        df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
        df = df.dropna(subset=['valor', 'fecha'])
        if df.empty:
            return None
        
        # Agrupar por día (promedio diario)
        df['fecha_dia'] = df['fecha'].dt.date
        df_diario = df.groupby('fecha_dia')['valor'].mean().reset_index()
        df_diario['fecha'] = pd.to_datetime(df_diario['fecha_dia'])
        df_diario = df_diario.sort_values('fecha')
        return df_diario[['fecha', 'valor']]
    except Exception as e:
        st.warning(f"Error en descarga: {e}")
        return None

# ===================================================================
# CONFIGURACIÓN DE LA PÁGINA
# ===================================================================
st.set_page_config(
    page_title="Visor Climático IDEAM",
    page_icon="🌦️",
    layout="wide"
)

st.title("🌦️ Visor de Datos Climáticos - IDEAM")
st.markdown("""
    Esta aplicación te permite explorar datos históricos de **precipitación y temperatura** 
    de las estaciones del IDEAM en Colombia.
    Ingresa coordenadas para encontrar las estaciones más cercanas.
""")

# ===================================================================
# SIDEBAR: CONFIGURACIÓN DE BÚSQUEDA
# ===================================================================
with st.sidebar:
    st.header("📍 Ubicación")
    lat = st.number_input("Latitud", value=4.7110, format="%.4f", step=0.001)
    lon = st.number_input("Longitud", value=-74.0721, format="%.4f", step=0.001)
    n_estaciones = st.slider("Número de estaciones cercanas", 1, 10, 5)
    buscar = st.button("🔍 Buscar estaciones", type="primary")

# ===================================================================
# CUERPO PRINCIPAL
# ===================================================================
if buscar:
    with st.spinner("Obteniendo estaciones cercanas..."):
        try:
            estaciones = get_stations_nearby(lat, lon, n_estaciones)
            if estaciones.empty:
                st.error("No se encontraron estaciones cercanas.")
                st.stop()
        except Exception as e:
            st.error(f"Error al obtener estaciones: {e}")
            st.stop()
    
    st.subheader("📌 Estaciones más cercanas")
    # Mostrar tabla con estilo
    st.dataframe(
        estaciones[['name', 'id', 'department', 'municipality']].rename(
            columns={'name': 'Nombre', 'id': 'Código', 'department': 'Departamento', 'municipality': 'Municipio'}
        ),
        use_container_width=True
    )
    
    # Selección de estación
    opciones = {f"{row['name']} ({row['id']})": row['id'] for _, row in estaciones.iterrows()}
    seleccion = st.selectbox("Selecciona una estación", list(opciones.keys()))
    codigo_seleccionado = opciones[seleccion]
    nombre_seleccionado = seleccion.split(" (")[0]
    
    # Selección de variable
    st.subheader("📊 Variables")
    variables = st.multiselect(
        "Elige las variables a descargar",
        options=["Precipitación", "Temperatura"],
        default=["Precipitación"]
    )
    
    # Filtro de fechas (opcional)
    st.subheader("📅 Rango de fechas")
    # Obtener fechas mínima y máxima de los datos (aproximado)
    year_min = 1970
    year_max = datetime.now().year
    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input("Fecha inicial", value=datetime(year_min, 1, 1), 
                                     min_value=datetime(1950, 1, 1), 
                                     max_value=datetime.now())
    with col2:
        fecha_fin = st.date_input("Fecha final", value=datetime.now(), 
                                  min_value=datetime(1950, 1, 1), 
                                  max_value=datetime.now())
    
    if st.button("📥 Descargar y graficar", type="primary"):
        # Diccionario de datasets
        datasets = {
            "Precipitación": "s54a-sgyg",
            "Temperatura": "sbwg-7ju4"
        }
        
        # Diccionario para almacenar DataFrames
        datos = {}
        with st.spinner("Descargando datos..."):
            for var in variables:
                dataset_id = datasets[var]
                df = descargar_datos_ideam(codigo_seleccionado, dataset_id)
                if df is not None:
                    # Filtrar por rango de fechas
                    df = df[(df['fecha'] >= pd.to_datetime(fecha_inicio)) & 
                            (df['fecha'] <= pd.to_datetime(fecha_fin))]
                    if not df.empty:
                        datos[var] = df
                    else:
                        st.warning(f"No hay datos para {var} en el rango seleccionado.")
                else:
                    st.warning(f"No se pudieron obtener datos de {var} para esta estación.")
        
        if not datos:
            st.error("No se descargaron datos para ninguna variable.")
            st.stop()
        
        # Mostrar gráficos y estadísticas
        st.subheader(f"📈 Datos de {nombre_seleccionado}")
        
        # Crear tabs para cada variable
        tabs = st.tabs(list(datos.keys()))
        for idx, (var, df) in enumerate(datos.items()):
            with tabs[idx]:
                # Estadísticas
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Promedio", f"{df['valor'].mean():.2f}")
                with col2:
                    st.metric("Máximo", f"{df['valor'].max():.2f}")
                with col3:
                    st.metric("Mínimo", f"{df['valor'].min():.2f}")
                with col4:
                    st.metric("Días con datos", f"{len(df)}")
                
                # Gráfico
                fig, ax = plt.subplots(figsize=(12, 5))
                color = 'blue' if var == "Precipitación" else 'red'
                ax.plot(df['fecha'], df['valor'], color=color, linewidth=1, alpha=0.7)
                ax.set_title(f"{var} - {nombre_seleccionado}", fontsize=14)
                ax.set_xlabel("Fecha")
                ax.set_ylabel("mm" if var == "Precipitación" else "°C")
                ax.grid(True, linestyle='--', alpha=0.6)
                plt.tight_layout()
                st.pyplot(fig)
                
                # Botón para descargar CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📄 Descargar datos de {var} (CSV)",
                    data=csv,
                    file_name=f"{nombre_seleccionado}_{var}_{fecha_inicio}_{fecha_fin}.csv",
                    mime='text/csv'
                )
else:
    st.info("🔍 Ingresa coordenadas en la barra lateral y presiona 'Buscar estaciones' para comenzar.")
    # Mostrar mapa de Colombia con ubicación por defecto
    st.map(pd.DataFrame({'lat': [4.7110], 'lon': [-74.0721]}))

# ===================================================================
# PIE DE PÁGINA
# ===================================================================
st.markdown("---")
st.caption("Datos proporcionados por el IDEAM a través de datos.gov.co. Aplicación creada con Streamlit.")