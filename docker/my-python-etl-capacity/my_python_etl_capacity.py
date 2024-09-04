import requests
import base64
import json
from datetime import datetime
import psycopg2
import pandas as pd
from io import BytesIO
import time
import psycopg2.extras
from psycopg2 import sql
import numpy as np
import psycopg2
from psycopg2.extensions import register_adapter, AsIs
import os

def add_numpy_int64_adapter():
    register_adapter(np.int64, lambda val: AsIs(val.item()))



def get_auth_token(conn, endpoint_auth, endpoint_check, username, password):
    table_name = os.getenv('DB_AUTH_TOKEN_TABLE_NAME')
    # Crear la tabla si no existe
    create_table_query = sql.SQL("""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        token TEXT NOT NULL
    );
    """).format(table_name=sql.Identifier(table_name))


    cursor = conn.cursor()
    cursor.execute(create_table_query)
    conn.commit()

    # Obtener el último token si existe
    select_query = sql.SQL('SELECT token FROM {table_name} ORDER BY id DESC LIMIT 1').format(table_name=sql.Identifier(table_name))
    cursor.execute(select_query)
    result = cursor.fetchone()

    if result:
        token = result[0]
        # Verificar si el token es válido
        smart_empresa = os.getenv('AUTH_SMART_EMPRESA')
        headers = {
            'Smart-Empresa': smart_empresa,
            "Authorization": f"Bearer {token}"
        }
        response = requests.get(endpoint_check, headers=headers)

        if response.status_code == 200:
            return token

    # Si no hay token o el token no es válido, obtener uno nuevo
    token = autenticar(endpoint_auth, username, password)

    # Borrar los datos existentes en la tabla
    delete_query = sql.SQL('DELETE FROM {table_name}').format(table_name=sql.Identifier(table_name))
    cursor.execute(delete_query)
    conn.commit()

    # Guardar el nuevo token en la base de datos
    insert_token_query = sql.SQL('INSERT INTO {table_name} (token) VALUES (%s)').format(table_name=sql.Identifier(table_name))
    cursor.execute(insert_token_query, (token,))
    conn.commit()
    cursor.close()

    return token


# Función para enviar una petición POST y autenticarse
def autenticar(endpoint, username, password):
    body = {
        "username": username,
        "password": password
    }
    response = requests.post(endpoint, json=body)
    if response.status_code == 200:
        return response.json()['token']
    else:
        print(f"Error en la autenticación: {response.status_code}")
        return None

# Función para enviar una petición GET con el token de autenticación y parámetros preprocesados
def hacer_peticion_get(endpoint, token, fecha_inicio=None, fecha_fin=None):
    body_param = {}
    if fecha_inicio:
        # Convertir la fecha de inicio a milisegundos desde la época Unix
        body_param['ts_inicio'] = int(datetime.strptime(fecha_inicio, "%Y-%m-%d").timestamp()) * 1000
    if fecha_fin:
        # Convertir la fecha de fin a milisegundos desde la época Unix
        body_param['ts_fin'] = int(datetime.strptime(fecha_fin, "%Y-%m-%d").timestamp()) * 1000

    # Codificar los parámetros en base64
    encoded_query_param = base64.b64encode(json.dumps(body_param).encode()).decode()
    smart_empresa = os.getenv('AUTH_SMART_EMPRESA')

    headers = {
        'Smart-Empresa': smart_empresa,
        "Authorization": f"Bearer {token}"
    }

    params = {
        "params": encoded_query_param
    }

    # Realizar la petición GET
    response = requests.get(endpoint, headers=headers, params=params)
    if response.status_code == 200:
        return response
    else:
        print(f"Info: estado de la peticion GET: {response.status_code}")
        return response

def verificar_y_crear_tabla(conn, nombre_tabla):
    """ Verifica si la tabla existe y si no, la crea. """
    # Asegurarse de que el nombre de la tabla es seguro para usar en una consulta SQL
    if not nombre_tabla.isidentifier():
        raise ValueError("El nombre de la tabla no es válido")

    cur = conn.cursor()
    query = sql.SQL("""
        CREATE TABLE IF NOT EXISTS {table_name} (
            nombreDispositivo TEXT,
            nombreZona TEXT,
            tipo TEXT,
            fecha TIMESTAMP,
            contador NUMERIC(10, 2)
        );
    """).format(table_name=sql.Identifier(nombre_tabla))
    cur.execute(query)
    conn.commit()
    cur.close()

# Ejemplo de uso
def obtener_fecha_mas_reciente(conn, nombre_tabla):
    """ Obtiene la fecha más reciente en la tabla especificada. """
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(fecha) FROM {nombre_tabla}")
    fecha_max = cur.fetchone()[0]
    cur.close()
    return fecha_max

def obtener_fecha_mas_antigua(conn, nombre_tabla):
    """ Obtiene la fecha más reciente en la tabla especificada. """
    cur = conn.cursor()
    cur.execute(f"SELECT MIN(fecha) FROM {nombre_tabla}")
    fecha_min = cur.fetchone()[0]
    cur.close()
    return fecha_min

import sys
from dateutil.relativedelta import relativedelta

def proceso_carga(conn, nombre_tabla, token, fecha_inicio, direccion='forward', incremento=relativedelta(months=5), max_iterations=50):
    n = 0
    while n < max_iterations:
        n += 1
        fecha_fin = fecha_inicio + incremento if direccion == 'forward' else fecha_inicio - incremento
        if direccion == "backward":
            aux = fecha_inicio
            fecha_inicio = fecha_fin
            fecha_fin = aux
        response = cargar_datos(conn, nombre_tabla, token, fecha_inicio.strftime("%Y-%m-%d"), fecha_fin.strftime("%Y-%m-%d"))
        if response.status_code != 200 or not response.content:
            break
        fecha_inicio = fecha_fin if direccion == 'forward' else fecha_inicio
        print('hecho un', direccion, n)

def cargar_datos(conn, nombre_tabla, token, fecha_inicio, fecha_fin):
            
    endpoint_datos = os.getenv('DATA_ENDPOINT')

    #inicio = time.time()
    resultado = hacer_peticion_get(endpoint_datos, token, fecha_inicio, fecha_fin)
    #fin = time.time()
    #tiempo_transcurrido = fin - inicio
    #print(f"La función hacer_peticion_get tardó {tiempo_transcurrido:.4f} segundos en ejecutarse.")
    if resultado.status_code == 200:
            # Suponiendo que 'resultado' es la respuesta de una solicitud HTTP exitosa
            #inicio = time.time()
            csv_bytes = resultado.content
            df = pd.read_csv(BytesIO(csv_bytes), keep_default_na=True)
        
            # Filtrar filas donde 'contador' no tiene valor
            df = df[df['contador'].notna()]
        
            # Obtener las fechas máxima y mínima del DataFrame
            max_fecha_df = pd.to_datetime(df['fecha'].max())  # Ajusta 'fecha' según el nombre de tu columna de fecha
            min_fecha_df = pd.to_datetime(df['fecha'].min())
            
            fecha_mas_reciente_db = obtener_fecha_mas_reciente(conn, nombre_tabla)
            fecha_mas_antigua_db = obtener_fecha_mas_antigua(conn, nombre_tabla)
            
            if fecha_mas_reciente_db is not None and fecha_mas_antigua_db is not None:
                if (fecha_mas_reciente_db == max_fecha_df or 
                    fecha_mas_antigua_db == min_fecha_df):
                    print("Info: parando por carga duplicada.", file=sys.stderr)
                    resultado.status_code = 0
                    return resultado
                               
                #Filtro para eliminar duplicados a la hora de cargar
                df = df[(pd.to_datetime(df['fecha']) > fecha_mas_reciente_db) | (pd.to_datetime(df['fecha']) < fecha_mas_antigua_db)]
            
            # Comprobar si la fecha fin es mayor que la fecha actual
            fecha_actual = datetime.now()
            if pd.to_datetime(fecha_fin) > fecha_actual:
                resultado.status_code = 0
                print("Info: terminando porque la fecha fin es mayor que la fecha actual.", file=sys.stderr)
        
            data_tuples = df.to_records(index=False)  # Convertir DataFrame a tuplas
        
            cur = conn.cursor()
        
            query = sql.SQL("INSERT INTO {table} (nombreDispositivo, nombreZona, tipo, fecha, contador) VALUES %s").format(table=sql.Identifier(nombre_tabla))
            # Ejecutar la consulta usando execute_values
            psycopg2.extras.execute_values(
                cur,
                query,
                data_tuples,
                template=None,
                page_size=2000  # Ejecuta la inserción en lotes de hasta 2000
            )
        
            conn.commit()
            cur.close()
            
            
            
            #fin = time.time()
            #tiempo_transcurrido = fin - inicio
            #print(f"La función cur.execute tardó {tiempo_transcurrido:.4f} segundos en ejecutarse.")
    else:
            print(f"Info: Finalizacion por {resultado.status_code} - {resultado.text} esperado.", file=sys.stderr)
        
    return resultado


def main():
    conn = psycopg2.connect(
        dbname= os.getenv('DB_NAME'), 
        user= os.getenv('DB_USER'), 
        password= os.getenv('DB_PASS'), 
        host= os.getenv('DB_HOST')
    )
    
    # Llama a esta función antes de realizar operaciones con la base de datos
    add_numpy_int64_adapter()
    
    nombre_tabla = os.getenv('DB_TABLE_NAME')
    verificar_y_crear_tabla(conn, nombre_tabla)

    fecha_max = obtener_fecha_mas_reciente(conn, nombre_tabla)
    fecha_min = obtener_fecha_mas_antigua(conn, nombre_tabla)

    fecha_actual = datetime.now()
    
    endpoint_datos = os.getenv('DATA_ENDPOINT')

    #autenticar
    endpoint_auth = os.getenv('AUTH_ENDPOINT')
    username = os.getenv('AUTH_USER')
    password = os.getenv('AUTH_PASS')
    token = get_auth_token(conn, endpoint_auth, endpoint_datos, username, password)
    if not token:
        print("Error: Autenticación fallida.", file=sys.stderr)
    else:

        # Proceso hacia adelante
        fecha_inicio_fow = fecha_max if fecha_max else fecha_actual
        proceso_carga(conn, nombre_tabla, token, fecha_inicio_fow, 'forward')

        # Proceso hacia atrás
        fecha_inicio_bak = fecha_min if fecha_min else fecha_actual
        proceso_carga(conn, nombre_tabla, token, fecha_inicio_bak, 'backward')

    conn.close()




if __name__ == "__main__":
    main()



