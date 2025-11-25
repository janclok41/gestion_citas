from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3, os, datetime, logging, uuid, time
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_socketio import SocketIO, emit, join_room
import threading
from contextlib import contextmanager
import re

# ===== CONFIGURACIÓN AVANZADA =====
APP_DB = os.path.join(os.path.dirname(__file__), 'citas_escalable.db')
app = Flask(__name__, static_folder='static', template_folder='templates')

# Configuración de seguridad MEJORADA
app.secret_key = 'clave_secreta_desarrollo_cambiar_en_produccion'
app.config['DEBUG'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configuración de SocketIO MEJORADA
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25,
    manage_session=False
)

# Configuración de logging avanzado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(threadName)s %(message)s',
    handlers=[
        logging.FileHandler('citas_system.log'),
        logging.StreamHandler()
    ]
)

# ===== GESTIÓN AVANZADA DE CONEXIONES =====
_db_connections = threading.local()

def get_db_connection():
    """Obtener conexión a la base de datos ultra optimizada"""
    conn = sqlite3.connect(APP_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    
    # CONFIGURACIÓN PARA ALTA ESCALABILIDAD
    conn.executescript('''
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA cache_size = -64000;
        PRAGMA temp_store = MEMORY;
        PRAGMA mmap_size = 134217728;
        PRAGMA auto_vacuum = INCREMENTAL;
        PRAGMA foreign_keys = ON;
        PRAGMA optimize;
        PRAGMA busy_timeout = 5000;
    ''')
    return conn

@contextmanager
def db_connection():
    """Context manager optimizado para manejo de conexiones"""
    conn = None
    try:
        if hasattr(_db_connections, 'conn'):
            conn = _db_connections.conn
            try:
                conn.execute("SELECT 1")
            except:
                conn = None
        
        if not conn:
            conn = get_db_connection()
            _db_connections.conn = conn
        
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"Error en conexión BD: {e}")
        raise e

def close_db_connection():
    """Cerrar conexión del thread actual"""
    if hasattr(_db_connections, 'conn'):
        try:
            _db_connections.conn.close()
        except:
            pass
        finally:
            if hasattr(_db_connections, 'conn'):
                delattr(_db_connections, 'conn')

@app.teardown_appcontext
def close_connection(exception=None):
    """Cerrar conexiones al final del request"""
    close_db_connection()

# ===== MIGRACIÓN DE BASE DE DATOS =====
def migrar_base_datos():
    """Migrar la base de datos existente para eliminar pagos"""
    with db_connection() as conn:
        try:
            # Verificar si la tabla pagos existe y eliminarla
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pagos'")
            if cursor.fetchone():
                app.logger.info("🔄 Migrando base de datos: eliminando tabla pagos...")
                
                # Eliminar tabla pagos
                conn.execute("DROP TABLE IF EXISTS pagos")
                
                # Actualizar índices
                conn.executescript('''
                    DROP INDEX IF EXISTS idx_pagos_estado_fecha;
                    DROP INDEX IF EXISTS idx_pagos_familia;
                    DROP INDEX IF EXISTS idx_pagos_cita;
                ''')
                
                conn.commit()
                app.logger.info("✅ Migración completada: tabla pagos eliminada")
            else:
                app.logger.info("✅ Base de datos ya no tiene tabla pagos")
                
        except Exception as e:
            app.logger.error(f"❌ Error en migración: {e}")
            conn.rollback()
            raise e

def reparar_base_datos():
    """Reparar la base de datos agregando columnas faltantes"""
    with db_connection() as conn:
        try:
            app.logger.info("🔧 Verificando estructura de la base de datos...")
            
            # Verificar si la columna cita_autorizada existe en citas
            cursor = conn.execute("PRAGMA table_info(citas)")
            columnas = [col[1] for col in cursor.fetchall()]
            
            # Agregar columna cita_autorizada si no existe
            if 'cita_autorizada' not in columnas:
                app.logger.info("🔄 Agregando columna cita_autorizada a tabla citas...")
                conn.execute('''
                    ALTER TABLE citas ADD COLUMN cita_autorizada BOOLEAN DEFAULT 0
                ''')
                app.logger.info("✅ Columna cita_autorizada agregada")
            
            # Verificar otras columnas necesarias
            columnas_necesarias = ['usuario_creador', 'fecha_actualizacion']
            for columna in columnas_necesarias:
                if columna not in columnas:
                    app.logger.info(f"🔄 Agregando columna {columna} a tabla citas...")
                    if columna == 'usuario_creador':
                        conn.execute(f'ALTER TABLE citas ADD COLUMN {columna} TEXT')
                    else:
                        conn.execute(f'ALTER TABLE citas ADD COLUMN {columna} TEXT DEFAULT CURRENT_TIMESTAMP')
                    app.logger.info(f"✅ Columna {columna} agregada")
            
            conn.commit()
            app.logger.info("✅ Base de datos reparada exitosamente")
            
        except Exception as e:
            app.logger.error(f"❌ Error reparando base de datos: {e}")
            conn.rollback()
            raise e

# ===== INICIALIZACIÓN DE BASE DE DATOS OPTIMIZADA =====
def init_db():
    """Inicializar la base de datos ultra optimizada"""
    with db_connection() as conn:
        cursor = conn.cursor()
        
        # TABLA USUARIOS - Optimizada para búsquedas rápidas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL COLLATE NOCASE,
                contrasena TEXT NOT NULL,
                rol TEXT NOT NULL CHECK(rol IN ('admin', 'profesional', 'coordinadora', 'administracion')),
                nombre_completo TEXT NOT NULL,
                color_calendario TEXT DEFAULT '#3498db',
                activo BOOLEAN DEFAULT 1,
                fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
                ultimo_acceso TEXT
            )
        ''')
        
        # TABLA FAMILIAS - Optimizada para 10,000+ registros
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS familias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombres_apellidos TEXT NOT NULL,
                tipo_identificacion TEXT NOT NULL,
                numero_identificacion TEXT UNIQUE NOT NULL,
                direccion TEXT,
                telefono_principal TEXT NOT NULL,
                telefono_secundario TEXT,
                email TEXT,
                nombre_hijo_hija TEXT NOT NULL,
                fecha_nacimiento_hijo TEXT,
                edad_actual INTEGER,
                fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
                activo BOOLEAN DEFAULT 1,
                notas TEXT
            )
        ''')
        
        # TABLA CITAS - Optimizada para consultas rápidas - SIN COMPONENTES DE PAGO
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS citas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                familia_id INTEGER NOT NULL,
                profesional_id INTEGER NOT NULL,
                fecha_hora TEXT NOT NULL,
                duracion INTEGER DEFAULT 60,
                tipo_consulta TEXT DEFAULT 'presencial',
                estado TEXT DEFAULT 'agendada',
                cita_autorizada BOOLEAN DEFAULT 0,
                notas TEXT,
                motivo_consulta TEXT,
                fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
                usuario_creador TEXT,
                fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (familia_id) REFERENCES familias(id) ON DELETE RESTRICT,
                FOREIGN KEY (profesional_id) REFERENCES usuarios(id) ON DELETE RESTRICT
            )
        ''')
        
        # TABLA ALERTAS - Sistema de notificaciones mejorado
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cita_id INTEGER,
                mensaje TEXT NOT NULL,
                usuario_destino TEXT,
                tipo TEXT DEFAULT 'info',
                leida BOOLEAN DEFAULT 0,
                fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
                fecha_leida TEXT,
                FOREIGN KEY (cita_id) REFERENCES citas(id) ON DELETE CASCADE
            )
        ''')
        
        # TABLA SESIONES ACTIVAS - Mejor seguridad
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sesiones_activas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL,
                session_id TEXT UNIQUE NOT NULL,
                fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
                ultima_actividad TEXT DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        
        # ÍNDICES AVANZADOS PARA MÁXIMO RENDIMIENTO
        cursor.executescript('''
            CREATE INDEX IF NOT EXISTS idx_usuarios_rol_activo ON usuarios(rol, activo);
            CREATE INDEX IF NOT EXISTS idx_usuarios_usuario ON usuarios(usuario);
            
            CREATE INDEX IF NOT EXISTS idx_familias_identificacion ON familias(numero_identificacion);
            CREATE INDEX IF NOT EXISTS idx_familias_telefono ON familias(telefono_principal);
            CREATE INDEX IF NOT EXISTS idx_familias_nombre ON familias(nombres_apellidos);
            CREATE INDEX IF NOT EXISTS idx_familias_hijo ON familias(nombre_hijo_hija);
            CREATE INDEX IF NOT EXISTS idx_familias_activo ON familias(activo);
            
            CREATE INDEX IF NOT EXISTS idx_citas_fecha_profesional ON citas(fecha_hora, profesional_id);
            CREATE INDEX IF NOT EXISTS idx_citas_estado_fecha ON citas(estado, fecha_hora);
            CREATE INDEX IF NOT EXISTS idx_citas_familia ON citas(familia_id);
            CREATE INDEX IF NOT EXISTS idx_citas_profesional ON citas(profesional_id);
            CREATE INDEX IF NOT EXISTS idx_citas_autorizada ON citas(cita_autorizada, estado);
            
            CREATE INDEX IF NOT EXISTS idx_alertas_usuario_leida ON alertas(usuario_destino, leida);
            CREATE INDEX IF NOT EXISTS idx_alertas_fecha ON alertas(fecha_creacion);
            
            CREATE INDEX IF NOT EXISTS idx_sesiones_usuario ON sesiones_activas(usuario);
            CREATE INDEX IF NOT EXISTS idx_sesiones_actividad ON sesiones_activas(ultima_actividad);
        ''')
        
        conn.commit()
        app.logger.info("✅ Base de datos optimizada creada exitosamente")

def crear_usuarios_iniciales():
    """Crear usuarios por defecto con seguridad mejorada"""
    with db_connection() as conn:
        cursor = conn.cursor()
        
        usuarios_por_defecto = [
            ("admin", "admin123", "admin", "Administrador del Sistema", "#e74c3c"),
            ("psicologa_ana", "Ana123!", "profesional", "Ana Martínez Silva - Psicóloga Infantil", "#3498db"),
            ("psicologo_carlos", "Carlos123!", "profesional", "Carlos López Ramírez - Terapeuta Familiar", "#2ecc71"),
            ("coordinadora", "Coord123!", "coordinadora", "Laura Rodríguez - Coordinadora de Psicología", "#9b59b6"),
            ("administracion", "Admin123!", "administracion", "Pedro Gómez - Administración de Autorizaciones", "#f39c12")
        ]
        
        for usuario, contrasena, rol, nombre_completo, color in usuarios_por_defecto:
            cursor.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO usuarios (usuario, contrasena, rol, nombre_completo, color_calendario) VALUES (?,?,?,?,?)", 
                    (usuario, generate_password_hash(contrasena), rol, nombre_completo, color)
                )
                app.logger.info(f"Usuario {usuario} creado")
        
        conn.commit()

def crear_familias_prueba():
    """Crear datos de prueba optimizados para familias"""
    with db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as c FROM familias")
        if cursor.fetchone()['c'] > 0:
            return
        
        familias_prueba = [
            ('María González López', 'Cédula', '123456789', 'Calle 123 #45-67, Bogotá', 
             '3001234567', '6012345678', 'maria.gonzalez@email.com', 'Sofía González', '2018-05-15', 6),
            
            ('Carlos Rodríguez Pérez', 'Cédula', '987654321', 'Av. Principal #89-10, Medellín', 
             '3109876543', '6023456789', 'carlos.rodriguez@email.com', 'Juan Rodríguez', '2019-08-22', 5),
            
            ('Ana Patricia Vargas', 'Cédula', '456789123', 'Carrera 56 #72-33, Cali', 
             '3204567890', '6029876543', 'ana.vargas@email.com', 'Miguel Vargas', '2017-11-30', 7),
            
            ('Roberto Sánchez Díaz', 'Cédula', '789123456', 'Diagonal 23 #44-55, Barranquilla', 
             '3157891234', '6051234567', 'roberto.sanchez@email.com', 'Valentina Sánchez', '2020-03-10', 4),
            
            ('Lucía Mendoza Herrera', 'Cédula', '321654987', 'Transversal 78 #12-34, Cartagena', 
             '3173216549', '6059876543', 'lucia.mendoza@email.com', 'Daniel Mendoza', '2016-12-05', 8)
        ]
        
        for familia in familias_prueba:
            cursor.execute('''
                INSERT INTO familias 
                (nombres_apellidos, tipo_identificacion, numero_identificacion, direccion, 
                 telefono_principal, telefono_secundario, email, nombre_hijo_hija, fecha_nacimiento_hijo, edad_actual) 
                VALUES (?,?,?,?,?,?,?,?,?,?)
            ''', familia)
        
        conn.commit()
    app.logger.info("✅ Datos de prueba de familias insertados")

# ===== VALIDACIONES DE SEGURIDAD MEJORADAS =====
def sanitizar_input(texto, max_length=255):
    """Sanitizar y validar input del usuario"""
    if not texto:
        return texto
    texto = str(texto).strip()
    # Eliminar caracteres potencialmente peligrosos
    texto = re.sub(r'[;\'"\\/*]', '', texto)
    # Limitar longitud
    return texto[:max_length]

def validar_email(email):
    """Validar formato de email"""
    if not email:
        return True
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validar_telefono(telefono):
    """Validar formato de teléfono"""
    if not telefono:
        return False
    # Permitir números, +, espacios y guiones
    telefono_limpio = re.sub(r'[\s\-+]', '', telefono)
    return telefono_limpio.isdigit() and 10 <= len(telefono_limpio) <= 15

def verificar_propiedad_cita(cita_id, usuario_id, rol):
    """Verificar que el usuario tiene permisos sobre la cita - MEJORADA"""
    with db_connection() as conn:
        cita = conn.execute(
            "SELECT profesional_id FROM citas WHERE id = ?", 
            (cita_id,)
        ).fetchone()
        
        if not cita:
            return False
            
        # Admin y coordinación pueden modificar cualquier cita
        if rol in ['admin', 'coordinadora']:
            return True
            
        # Profesionales solo pueden modificar sus propias citas
        return cita['profesional_id'] == usuario_id

# ===== GESTIÓN MEJORADA DE SESIONES =====
def crear_sesion(usuario, session_id, ip_address=None, user_agent=None):
    """Crear o actualizar sesión activa con seguridad mejorada"""
    with db_connection() as conn:
        try:
            # Limpiar sesiones expiradas (más de 2 horas)
            conn.execute(
                "DELETE FROM sesiones_activas WHERE datetime('now') > datetime(ultima_actividad, '+2 hours')"
            )
            
            # Eliminar sesiones existentes del mismo usuario
            conn.execute("DELETE FROM sesiones_activas WHERE usuario = ?", (usuario,))
            
            # Crear nueva sesión
            conn.execute(
                "INSERT INTO sesiones_activas (usuario, session_id, fecha_creacion, ultima_actividad, ip_address, user_agent) VALUES (?,?,datetime('now'),datetime('now'),?,?)",
                (usuario, session_id, ip_address, user_agent)
            )
            conn.commit()
            app.logger.info(f"✅ Sesión creada para {usuario}")
            return True
        except Exception as e:
            app.logger.error(f"❌ Error al crear sesión: {e}")
            conn.rollback()
            return False

def verificar_sesion_valida(usuario, session_id):
    """Verificar si la sesión actual es válida - VERSIÓN SIMPLIFICADA Y ROBUSTA"""
    if not usuario or not session_id:
        app.logger.warning("❌ Verificación fallida: usuario o session_id vacíos")
        return False
        
    with db_connection() as conn:
        try:
            # Consulta simplificada - solo verificar existencia
            sesion = conn.execute(
                "SELECT id FROM sesiones_activas WHERE usuario = ? AND session_id = ?",
                (usuario, session_id)
            ).fetchone()
            
            if sesion:
                app.logger.info(f"✅ Sesión válida encontrada para {usuario}")
                # Actualizar última actividad
                conn.execute(
                    "UPDATE sesiones_activas SET ultima_actividad = datetime('now') WHERE id = ?",
                    (sesion['id'],)
                )
                conn.commit()
                return True
            else:
                app.logger.warning(f"❌ No se encontró sesión para {usuario}")
                return False
                
        except Exception as e:
            app.logger.error(f"❌ Error en verificar_sesion_valida: {e}")
            # En caso de error en la BD, permitir acceso por seguridad
            return True

def cerrar_sesion_db(usuario):
    """Cerrar sesión en la base de datos"""
    with db_connection() as conn:
        try:
            conn.execute("DELETE FROM sesiones_activas WHERE usuario = ?", (usuario,))
            conn.commit()
            app.logger.info(f"✅ Sesión cerrada para {usuario}")
        except Exception as e:
            app.logger.error(f"❌ Error al cerrar sesión en BD: {e}")

def verificar_sesion(f):
    """Decorador MEJORADO para verificar la validez de la sesión - VERSIÓN ROBUSTA"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Permitir acceso a login sin verificación
        if request.endpoint == 'login':
            return f(*args, **kwargs)
        
        app.logger.info(f"🔍 Verificando sesión para {request.endpoint}")
        
        # Verificar si existe sesión en flask session
        if 'usuario' not in session or 'session_id' not in session:
            app.logger.warning("❌ No hay sesión activa en Flask - Redirigiendo a login")
            flash('🔒 Debe iniciar sesión para acceder a esta página', 'warning')
            return redirect(url_for('login'))
        
        app.logger.info(f"✅ Sesión Flask encontrada: {session['usuario']}")
        
        # Verificar validez de la sesión en BD
        try:
            es_valida = verificar_sesion_valida(session['usuario'], session['session_id'])
            
            if not es_valida:
                app.logger.warning("❌ Sesión inválida en BD - Redirigiendo a login")
                usuario = session.get('usuario')
                session.clear()
                flash('🔒 Su sesión ha expirado. Por favor, inicie sesión nuevamente.', 'warning')
                return redirect(url_for('login'))
                
        except Exception as e:
            app.logger.error(f"❌ Error verificando sesión en BD: {e}")
            # En caso de error, permitir el acceso por seguridad
            app.logger.warning("⚠️ Error en verificación BD, permitiendo acceso temporal")
        
        app.logger.info("✅ Acceso permitido a " + str(request.endpoint))
        return f(*args, **kwargs)
    return decorated_function

# ===== DECORADOR PARA ROLES MEJORADO =====
def requiere_rol(roles_permitidos):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'rol' not in session:
                flash('🔒 Acceso denegado. Rol no identificado.', 'danger')
                return redirect(url_for('login'))
            
            if session['rol'] not in roles_permitidos:
                flash('🔒 No tienes permisos para acceder a esta sección.', 'danger')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ===== SISTEMA DE NOTIFICACIONES MEJORADO - OPTIMIZADO =====
@socketio.on('connect')
def handle_connect():
    """Manejar conexión de WebSocket mejorado"""
    app.logger.info(f"🔌 WebSocket: Cliente conectado - SID: {request.sid}")
    
    if 'usuario' in session and 'rol' in session:
        room_usuario = f"user_{session['usuario']}"
        room_rol = f"rol_{session['rol']}"
        
        join_room(room_usuario)
        join_room(room_rol)
        
        app.logger.info(f"🔌 WebSocket: Usuario {session['usuario']} unido a salas: {room_usuario}, {room_rol}")
        
        emit('connection_established', {
            'message': 'Conectado al sistema de notificaciones', 
            'usuario': session['usuario'],
            'rol': session['rol']
        }, room=room_usuario)

@socketio.on('join_rooms')
def handle_join_rooms():
    """Manejar solicitud de unión a salas"""
    if 'usuario' in session and 'rol' in session:
        room_usuario = f"user_{session['usuario']}"
        room_rol = f"rol_{session['rol']}"
        
        join_room(room_usuario)
        join_room(room_rol)
        
        app.logger.info(f"🔌 WebSocket: Usuario {session['usuario']} unido a salas automáticamente")

def enviar_notificacion_tiempo_real(mensaje, usuario_destino=None, rol_destino=None, tipo='info'):
    """Enviar notificación en tiempo real mejorada - CON DESTINOS MÚLTIPLES"""
    data = {
        'mensaje': mensaje,
        'timestamp': datetime.datetime.now().isoformat(),
        'tipo': tipo,
        'id': str(uuid.uuid4())[:8]
    }
    
    try:
        app.logger.info(f"📨 Enviando notificación: {mensaje}")
        app.logger.info(f"📨 Destinos - Usuario: {usuario_destino}, Rol: {rol_destino}")
        
        if usuario_destino:
            # Notificación individual
            room_usuario = f"user_{usuario_destino}"
            socketio.emit('nueva_notificacion', data, room=room_usuario)
            app.logger.info(f"📨 Notificación enviada a usuario: {usuario_destino} (Sala: {room_usuario})")
        
        if rol_destino:
            # Notificación por rol
            room_rol = f"rol_{rol_destino}"
            socketio.emit('nueva_notificacion', data, room=room_rol)
            app.logger.info(f"📨 Notificación enviada a rol: {rol_destino} (Sala: {room_rol})")
            
        # Actualizar contadores para todos los afectados
        if usuario_destino or rol_destino:
            socketio.emit('actualizar_contador', {}, room='all_users')
            
        return True
    except Exception as e:
        app.logger.error(f"❌ Error enviando notificación WebSocket: {e}")
        return False

def crear_alerta_mejorada(cita_id, mensaje, usuario_destino=None, rol_destino=None, tipo='info'):
    """Crear alerta en la base de datos mejorada - CON DESTINOS MÚLTIPLES"""
    with db_connection() as conn:
        try:
            alertas_creadas = []
            
            # Si se especifica rol_destino, buscar usuarios con ese rol
            if rol_destino:
                usuarios_destino = conn.execute(
                    "SELECT usuario FROM usuarios WHERE rol = ? AND activo = 1", 
                    (rol_destino,)
                ).fetchall()
                
                for usuario in usuarios_destino:
                    cursor = conn.execute(
                        "INSERT INTO alertas (cita_id, mensaje, usuario_destino, tipo) VALUES (?,?,?,?)",
                        (cita_id, mensaje, usuario['usuario'], tipo)
                    )
                    alertas_creadas.append(cursor.lastrowid)
            
            # Si se especifica usuario_destino individual
            if usuario_destino:
                cursor = conn.execute(
                    "INSERT INTO alertas (cita_id, mensaje, usuario_destino, tipo) VALUES (?,?,?,?)",
                    (cita_id, mensaje, usuario_destino, tipo)
                )
                alertas_creadas.append(cursor.lastrowid)
            
            conn.commit()
            
            # Enviar notificación en tiempo real
            enviar_notificacion_tiempo_real(mensaje, usuario_destino, rol_destino, tipo)
                
            return alertas_creadas
        except Exception as e:
            app.logger.error(f"Error creando alerta: {e}")
            conn.rollback()
            return False

def obtener_alertas_no_leidas(usuario, rol):
    """Obtener alertas no leídas optimizado - MEJORADO PARA ROLES"""
    with db_connection() as conn:
        try:
            if rol in ['admin', 'coordinadora']:
                # Admin y coordinación ven alertas de todos
                alertas = conn.execute("""
                    SELECT a.*, c.id as cita_id, f.nombres_apellidos as familia_nombre,
                           u.nombre_completo as profesional_nombre
                    FROM alertas a 
                    LEFT JOIN citas c ON c.id = a.cita_id
                    LEFT JOIN familias f ON f.id = c.familia_id
                    LEFT JOIN usuarios u ON c.profesional_id = u.id
                    WHERE (a.usuario_destino IS NULL OR a.usuario_destino = ?) AND a.leida = 0
                    ORDER BY a.fecha_creacion DESC
                    LIMIT 50
                """, (usuario,)).fetchall()
            else:
                # Profesionales y administración ven solo sus alertas
                alertas = conn.execute("""
                    SELECT a.*, c.id as cita_id, f.nombres_apellidos as familia_nombre,
                           u.nombre_completo as profesional_nombre
                    FROM alertas a 
                    LEFT JOIN citas c ON c.id = a.cita_id
                    LEFT JOIN familias f ON f.id = c.familia_id
                    LEFT JOIN usuarios u ON c.profesional_id = u.id
                    WHERE a.usuario_destino = ? AND a.leida = 0
                    ORDER BY a.fecha_creacion DESC
                    LIMIT 50
                """, (usuario,)).fetchall()
            
            return alertas
        except Exception as e:
            app.logger.error(f"Error obteniendo alertas: {e}")
            return []

# ===== NUEVAS FUNCIONES PARA CONTADORES ESPECÍFICOS =====
def obtener_contadores_especificos(usuario, rol):
    """Obtener contadores específicos para cada sección - CORREGIDO"""
    with db_connection() as conn:
        try:
            contadores = {
                'alertas': 0,
                'autorizaciones_pendientes': 0,
                'citas_hoy': 0,
                'citas_pendientes': 0
            }
            
            # Contador de alertas (sin cambios)
            if rol in ['admin', 'coordinadora']:
                contadores['alertas'] = conn.execute("""
                    SELECT COUNT(*) as c FROM alertas 
                    WHERE (usuario_destino IS NULL OR usuario_destino = ?) AND leida = 0
                """, (usuario,)).fetchone()['c']
            else:
                contadores['alertas'] = conn.execute("""
                    SELECT COUNT(*) as c FROM alertas 
                    WHERE usuario_destino = ? AND leida = 0
                """, (usuario,)).fetchone()['c']
            
            # Contador de autorizaciones pendientes
            if rol in ['admin', 'administracion', 'coordinadora']:
                contadores['autorizaciones_pendientes'] = conn.execute("""
                    SELECT COUNT(*) as c FROM citas 
                    WHERE cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')
                """).fetchone()['c']
            
            # CORRECCIÓN: Contador de citas hoy - según rol
            if rol == 'profesional':
                # Para profesionales: solo sus citas de hoy
                user_id = session.get('user_id')
                if user_id:
                    contadores['citas_hoy'] = conn.execute("""
                        SELECT COUNT(*) as c FROM citas 
                        WHERE profesional_id = ? AND date(fecha_hora) = date('now')
                    """, (user_id,)).fetchone()['c']
            else:
                # Para admin/coordinación: todas las citas de hoy
                contadores['citas_hoy'] = conn.execute("""
                    SELECT COUNT(*) as c FROM citas 
                    WHERE date(fecha_hora) = date('now')
                """).fetchone()['c']
            
            # Contador de citas pendientes
            if rol == 'profesional':
                user_id = session.get('user_id')
                if user_id:
                    contadores['citas_pendientes'] = conn.execute("""
                        SELECT COUNT(*) as c FROM citas 
                        WHERE profesional_id = ? AND estado IN ('agendada', 'confirmada')
                    """, (user_id,)).fetchone()['c']
            else:
                contadores['citas_pendientes'] = conn.execute("""
                    SELECT COUNT(*) as c FROM citas 
                    WHERE estado IN ('agendada', 'confirmada')
                """).fetchone()['c']
            
            return contadores
            
        except Exception as e:
            app.logger.error(f"Error obteniendo contadores específicos: {e}")
            return contadores

def obtener_clase_badge(numero):
    """Obtener clase CSS según el número para ajustar tamaño"""
    if numero > 99:
        return 'huge-number'
    elif numero > 9:
        return 'large-number'
    return ''

@app.context_processor
def inject_alert_count():
    """Inyectar contador de alertas en todos los templates - OPTIMIZADO"""
    alert_count = 0
    badge_class = ''
    
    if 'usuario' in session and 'rol' in session:
        try:
            contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
            alert_count = contadores['alertas']
            badge_class = obtener_clase_badge(alert_count)
        except Exception as e:
            app.logger.error(f"Error en inject_alert_count: {e}")
            alert_count = 0
    
    return dict(
        alert_count=alert_count,
        badge_class=badge_class,
        obtener_clase_badge=obtener_clase_badge
    )

# ===== NUEVAS FUNCIONES PARA AUTORIZACIÓN DE CITAS =====
def autorizar_cita(cita_id, usuario_autorizador):
    """Autorizar una cita para que pueda ser atendida - NUEVA FUNCIÓN MEJORADA"""
    with db_connection() as conn:
        try:
            # Obtener información de la cita
            cita = conn.execute('''
                SELECT c.*, f.nombres_apellidos, u.usuario as profesional_usuario, 
                       u.nombre_completo as profesional_nombre, u2.usuario as usuario_creador
                FROM citas c
                JOIN familias f ON c.familia_id = f.id
                JOIN usuarios u ON c.profesional_id = u.id
                LEFT JOIN usuarios u2 ON c.usuario_creador = u2.usuario
                WHERE c.id = ?
            ''', (cita_id,)).fetchone()
            
            if not cita:
                return False, "Cita no encontrada"
            
            # Autorizar la cita
            conn.execute(
                "UPDATE citas SET cita_autorizada = 1, fecha_actualizacion = datetime('now') WHERE id = ?",
                (cita_id,)
            )
            
            # Crear notificación para el profesional que creó la cita
            mensaje_profesional = f"✅ Cita autorizada #{cita_id} con {cita['nombres_apellidos']}. Ya puede marcar como atendida."
            crear_alerta_mejorada(cita_id, mensaje_profesional, usuario_destino=cita['usuario_creador'], tipo='success')
            
            # Notificación para coordinación
            crear_alerta_mejorada(cita_id, f"📋 Cita autorizada por {usuario_autorizador} para cita #{cita_id}", rol_destino='coordinadora', tipo='info')
            
            conn.commit()
            app.logger.info(f"Cita #{cita_id} autorizada por {usuario_autorizador}")
            return True, "Cita autorizada exitosamente"
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error autorizando cita: {e}")
            return False, f"Error al autorizar cita: {str(e)}"

def rechazar_autorizacion_cita(cita_id, usuario_autorizador, motivo=""):
    """Rechazar autorización de una cita - NUEVA FUNCIÓN"""
    with db_connection() as conn:
        try:
            # Obtener información de la cita
            cita = conn.execute('''
                SELECT c.*, f.nombres_apellidos, u.usuario as profesional_usuario, u2.usuario as usuario_creador
                FROM citas c
                JOIN familias f ON c.familia_id = f.id
                JOIN usuarios u ON c.profesional_id = u.id
                LEFT JOIN usuarios u2 ON c.usuario_creador = u2.usuario
                WHERE c.id = ?
            ''', (cita_id,)).fetchone()
            
            if not cita:
                return False, "Cita no encontrada"
            
            # Rechazar la autorización
            conn.execute(
                "UPDATE citas SET cita_autorizada = 0, fecha_actualizacion = datetime('now') WHERE id = ?",
                (cita_id,)
            )
            
            # Crear notificación para el profesional
            mensaje = f"❌ Autorización rechazada para cita #{cita_id} con {cita['nombres_apellidos']}. {motivo}"
            crear_alerta_mejorada(cita_id, mensaje, usuario_destino=cita['usuario_creador'], tipo='danger')
            
            conn.commit()
            app.logger.info(f"Autorización rechazada para cita #{cita_id} por {usuario_autorizador}")
            return True, "Autorización rechazada exitosamente"
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error rechazando autorización: {e}")
            return False, f"Error al rechazar autorización: {str(e)}"

# ===== RUTAS PRINCIPALES MEJORADAS =====
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = sanitizar_input(request.form.get('usuario', ''))
        contrasena = request.form.get('contrasena', '')
        
        # Validación de rate limiting básico
        if 'intentos_login' not in session:
            session['intentos_login'] = 0
            session['primer_intento'] = time.time()
        
        # Bloquear después de 5 intentos en 5 minutos
        if session['intentos_login'] >= 5:
            tiempo_transcurrido = time.time() - session['primer_intento']
            if tiempo_transcurrido < 300:  # 5 minutos
                flash('🔒 Demasiados intentos fallidos. Espere 5 minutos.', 'danger')
                return redirect(url_for('login'))
            else:
                # Resetear contador después de 5 minutos
                session['intentos_login'] = 0
                session['primer_intento'] = time.time()
        
        if not usuario or not contrasena:
            flash('Usuario y contraseña son requeridos', 'danger')
            session['intentos_login'] += 1
            return redirect(url_for('login'))
        
        # Validación básica de seguridad
        if len(usuario) > 50 or len(contrasena) > 100:
            flash('Credenciales inválidas', 'danger')
            session['intentos_login'] += 1
            return redirect(url_for('login'))
        
        with db_connection() as conn:
            try:
                user = conn.execute(
                    "SELECT * FROM usuarios WHERE usuario = ? AND activo = 1", 
                    (usuario,)
                ).fetchone()
                
                if user and check_password_hash(user['contrasena'], contrasena):
                    session_id = str(uuid.uuid4())
                    
                    # Resetear contador de intentos
                    session['intentos_login'] = 0
                    
                    # Actualizar último acceso
                    conn.execute(
                        "UPDATE usuarios SET ultimo_acceso = datetime('now') WHERE id = ?",
                        (user['id'],)
                    )
                    
                    # Crear sesión segura
                    crear_sesion(
                        user['usuario'], 
                        session_id, 
                        request.remote_addr,
                        request.headers.get('User-Agent')
                    )
                    
                    session['usuario'] = user['usuario']
                    session['rol'] = user['rol']
                    session['user_id'] = user['id']
                    session['session_id'] = session_id
                    session['nombre_completo'] = user['nombre_completo']
                    session['color_calendario'] = user['color_calendario']
                    
                    conn.commit()
                    
                    app.logger.info(f"✅ Login exitoso: {user['usuario']} desde {request.remote_addr}")
                    flash(f'Bienvenido/a {user["nombre_completo"]}', 'success')
                    return redirect(url_for('dashboard'))
                else:
                    session['intentos_login'] += 1
                    app.logger.warning(f"❌ Intento de login fallido: {usuario} desde {request.remote_addr}")
                    flash('Usuario o contraseña incorrectos', 'danger')
                    return redirect(url_for('login'))
                    
            except Exception as e:
                conn.rollback()
                app.logger.error(f"❌ Error en login: {e}")
                flash('Error en el sistema. Intente nuevamente.', 'danger')
                return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
@verificar_sesion
def logout():
    usuario = session.get('usuario')
    cerrar_sesion_db(usuario)
    session.clear()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@verificar_sesion
def dashboard():
    with db_connection() as conn:
        stats = {}
        
        if session['rol'] in ['admin', 'coordinadora']:
            # Estadísticas generales optimizadas
            stats['total_citas'] = conn.execute("SELECT COUNT(*) as c FROM citas").fetchone()['c']
            stats['citas_hoy'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE date(fecha_hora) = date('now')"
            ).fetchone()['c']
            stats['citas_pendientes'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE estado IN ('agendada', 'confirmada')"
            ).fetchone()['c']
            stats['total_familias'] = conn.execute("SELECT COUNT(*) as c FROM familias WHERE activo = 1").fetchone()['c']
            # Verificar si existe la columna antes de usarla
            try:
                stats['citas_sin_autorizar'] = conn.execute(
                    "SELECT COUNT(*) as c FROM citas WHERE cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')"
                ).fetchone()['c']
            except:
                stats['citas_sin_autorizar'] = 0
        
        elif session['rol'] == 'profesional':
            # Estadísticas del profesional optimizadas
            stats['mis_citas_hoy'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE profesional_id = ? AND date(fecha_hora) = date('now')",
                (session['user_id'],)
            ).fetchone()['c']
            stats['mis_citas_pendientes'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE profesional_id = ? AND estado IN ('agendada', 'confirmada')",
                (session['user_id'],)
            ).fetchone()['c']
            stats['mis_citas_confirmadas'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE profesional_id = ? AND estado = 'confirmada'",
                (session['user_id'],)
            ).fetchone()['c']
            stats['mis_citas_semana'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE profesional_id = ? AND date(fecha_hora) BETWEEN date('now') AND date('now', '+7 days')",
                (session['user_id'],)
            ).fetchone()['c']
            # Verificar si existe la columna antes de usarla
            try:
                stats['mis_citas_sin_autorizar'] = conn.execute(
                    "SELECT COUNT(*) as c FROM citas WHERE profesional_id = ? AND cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')",
                    (session['user_id'],)
                ).fetchone()['c']
            except:
                stats['mis_citas_sin_autorizar'] = 0
        
        elif session['rol'] == 'administracion':
            # Estadísticas de autorizaciones optimizadas
            try:
                stats['citas_sin_autorizar'] = conn.execute(
                    "SELECT COUNT(*) as c FROM citas WHERE cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')"
                ).fetchone()['c']
            except:
                stats['citas_sin_autorizar'] = 0
            try:
                stats['citas_autorizadas_hoy'] = conn.execute(
                    "SELECT COUNT(*) as c FROM citas WHERE cita_autorizada = 1 AND date(fecha_actualizacion) = date('now')"
                ).fetchone()['c']
            except:
                stats['citas_autorizadas_hoy'] = 0
            stats['total_citas_pendientes'] = conn.execute(
                "SELECT COUNT(*) as c FROM citas WHERE estado IN ('agendada', 'confirmada')"
            ).fetchone()['c']
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('dashboard.html', 
                         usuario=session.get('usuario'), 
                         rol=session.get('rol'),
                         nombre_completo=session.get('nombre_completo'),
                         stats=stats,
                         contadores=contadores)

@app.route('/calendario')
@verificar_sesion
@requiere_rol(['admin', 'profesional', 'coordinadora'])
def calendario():
    with db_connection() as conn:
        # Obtener citas optimizadas según el rol
        if session['rol'] == 'profesional':
            citas = conn.execute('''
                SELECT c.*, f.nombres_apellidos as familia_nombre, f.nombre_hijo_hija, f.telefono_principal,
                       f.direccion, f.email, f.tipo_identificacion, f.numero_identificacion,
                       u.nombre_completo as profesional_nombre, u.color_calendario
                FROM citas c
                JOIN familias f ON c.familia_id = f.id
                JOIN usuarios u ON c.profesional_id = u.id
                WHERE c.profesional_id = ? AND c.fecha_hora >= datetime('now', '-1 day')
                ORDER BY c.fecha_hora
                LIMIT 100
            ''', (session['user_id'],)).fetchall()
        else:
            citas = conn.execute('''
                SELECT c.*, f.nombres_apellidos as familia_nombre, f.nombre_hijo_hija, f.telefono_principal,
                       f.direccion, f.email, f.tipo_identificacion, f.numero_identificacion,
                       u.nombre_completo as profesional_nombre, u.color_calendario
                FROM citas c
                JOIN familias f ON c.familia_id = f.id
                JOIN usuarios u ON c.profesional_id = u.id
                WHERE c.fecha_hora >= datetime('now', '-1 day')
                ORDER BY c.fecha_hora
                LIMIT 100
            ''').fetchall()
        
        # Obtener profesionales para el formulario
        profesionales = conn.execute(
            "SELECT id, nombre_completo, color_calendario FROM usuarios WHERE rol = 'profesional' AND activo = 1"
        ).fetchall()
        
        # Obtener familias para el formulario (limitado para mejor performance)
        familias = conn.execute(
            "SELECT id, nombres_apellidos, nombre_hijo_hija FROM familias WHERE activo = 1 ORDER BY nombres_apellidos LIMIT 100"
        ).fetchall()
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('calendario.html', 
                         citas=citas, 
                         profesionales=profesionales,
                         familias=familias,
                         rol=session['rol'],
                         contadores=contadores)

@app.route('/citas/agendar', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin', 'profesional', 'coordinadora'])
def agendar_cita():
    try:
        familia_id = request.form.get('familia_id')
        profesional_id = request.form.get('profesional_id')
        fecha_hora = request.form.get('fecha_hora')
        duracion = request.form.get('duracion', 60)
        tipo_consulta = request.form.get('tipo_consulta', 'presencial')
        notas = sanitizar_input(request.form.get('notas', ''), 500)
        motivo_consulta = sanitizar_input(request.form.get('motivo_consulta', ''), 200)
        
        # Validaciones mejoradas
        if not all([familia_id, profesional_id, fecha_hora]):
            flash('Familia, profesional y fecha/hora son requeridos', 'danger')
            return redirect(url_for('calendario'))
        
        # Validar fecha futura
        fecha_cita = datetime.datetime.fromisoformat(fecha_hora.replace('T', ' '))
        if fecha_cita < datetime.datetime.now():
            flash('No se pueden agendar citas en fechas pasadas', 'danger')
            return redirect(url_for('calendario'))
        
        with db_connection() as conn:
            # Verificar que no hay citas solapadas
            cita_existente = conn.execute('''
                SELECT id FROM citas 
                WHERE profesional_id = ? AND fecha_hora = ? AND estado NOT IN ('cancelada', 'no_atendida')
            ''', (profesional_id, fecha_hora)).fetchone()
            
            if cita_existente:
                flash('El profesional ya tiene una cita programada en ese horario', 'danger')
                return redirect(url_for('calendario'))
            
            # Crear la cita (cita_autorizada por defecto es 0 - no autorizada)
            cursor = conn.execute('''
                INSERT INTO citas 
                (familia_id, profesional_id, fecha_hora, duracion, tipo_consulta, notas, motivo_consulta, usuario_creador, cita_autorizada)
                VALUES (?,?,?,?,?,?,?,?,0)
            ''', (familia_id, profesional_id, fecha_hora, duracion, tipo_consulta, notas, motivo_consulta, session['usuario']))
            
            cita_id = cursor.lastrowid
            
            # Obtener información para notificaciones
            familia_info = conn.execute(
                "SELECT nombres_apellidos, nombre_hijo_hija FROM familias WHERE id = ?", 
                (familia_id,)
            ).fetchone()
            
            profesional_info = conn.execute(
                "SELECT usuario, nombre_completo FROM usuarios WHERE id = ?", 
                (profesional_id,)
            ).fetchone()
            
            # SISTEMA DE NOTIFICACIONES MEJORADO - EN TIEMPO REAL
            mensaje_alerta = f"📅 Nueva cita agendada con {familia_info['nombres_apellidos']} - {familia_info['nombre_hijo_hija']} para {fecha_hora[:16]}"
            
            # Notificación INMEDIATA a Administración y Coordinación
            crear_alerta_mejorada(cita_id, mensaje_alerta, rol_destino='administracion', tipo='warning')
            crear_alerta_mejorada(cita_id, mensaje_alerta, rol_destino='coordinadora', tipo='info')
            
            # Notificación al profesional si no fue él quien agendó
            if session['usuario'] != profesional_info['usuario']:
                crear_alerta_mejorada(cita_id, f"📅 Tienes una nueva cita agendada para {fecha_hora[:16]}", 
                                    usuario_destino=profesional_info['usuario'], tipo='info')
            
            conn.commit()
            
            app.logger.info(f"Cita #{cita_id} agendada por {session['usuario']}")
            flash('Cita agendada exitosamente. Esperando autorización.', 'success')
            
    except ValueError as e:
        flash('Formato de fecha inválido', 'danger')
        app.logger.error(f"Error de formato en agendar cita: {e}")
    except Exception as e:
        app.logger.error(f"Error agendando cita: {e}")
        flash('Error al agendar la cita', 'danger')
    
    return redirect(url_for('calendario'))

# ===== NUEVAS RUTAS PARA AUTORIZACIÓN DE CITAS =====
@app.route('/citas/<int:cita_id>/autorizar', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin', 'administracion'])
def autorizar_cita_route(cita_id):
    """Ruta para autorizar una cita"""
    success, message = autorizar_cita(cita_id, session['usuario'])
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    
    return redirect(url_for('gestion_citas'))

@app.route('/citas/<int:cita_id>/rechazar_autorizacion', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin', 'administracion'])
def rechazar_autorizacion_cita_route(cita_id):
    """Ruta para rechazar autorización de una cita"""
    motivo = sanitizar_input(request.form.get('motivo', 'Pendiente de verificación'))
    success, message = rechazar_autorizacion_cita(cita_id, session['usuario'], motivo)
    
    if success:
        flash(message, 'info')
    else:
        flash(message, 'danger')
    
    return redirect(url_for('gestion_citas'))

# ===== NUEVA RUTA PARA ELIMINAR CITAS =====
@app.route('/citas/<int:cita_id>/eliminar', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin', 'coordinadora'])
def eliminar_cita(cita_id):
    """Eliminar una cita del sistema"""
    with db_connection() as conn:
        try:
            # Verificar que la cita existe
            cita = conn.execute(
                "SELECT * FROM citas WHERE id = ?", 
                (cita_id,)
            ).fetchone()
            
            if not cita:
                flash('Cita no encontrada', 'danger')
                return redirect(url_for('gestion_citas'))
            
            # Eliminar la cita
            conn.execute("DELETE FROM citas WHERE id = ?", (cita_id,))
            
            # Eliminar alertas relacionadas
            conn.execute("DELETE FROM alertas WHERE cita_id = ?", (cita_id,))
            
            conn.commit()
            
            app.logger.info(f"Cita #{cita_id} eliminada por {session['usuario']}")
            flash('Cita eliminada exitosamente', 'success')
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error eliminando cita: {e}")
            flash('Error al eliminar la cita', 'danger')
    
    return redirect(url_for('gestion_citas'))

# ===== NUEVA RUTA PARA LIMPIAR TODAS LAS CITAS =====
@app.route('/admin/limpiar_citas', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin'])
def limpiar_citas():
    """Limpiar todas las citas (solo para desarrollo)"""
    with db_connection() as conn:
        try:
            # Eliminar todas las citas
            conn.execute("DELETE FROM citas")
            # Eliminar todas las alertas
            conn.execute("DELETE FROM alertas")
            conn.commit()
            
            app.logger.info(f"Todas las citas limpiadas por {session['usuario']}")
            flash('✅ Todas las citas han sido eliminadas. Base de datos limpia.', 'success')
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error limpiando citas: {e}")
            flash('Error al limpiar las citas', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/citas/<int:cita_id>/actualizar_estado', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin', 'profesional', 'coordinadora'])
def actualizar_estado_cita(cita_id):
    nuevo_estado = request.form.get('estado')
    notas = sanitizar_input(request.form.get('notas', ''), 500)
    
    if not nuevo_estado:
        flash('Estado es requerido', 'danger')
        return redirect(url_for('calendario'))
    
    # Validar que el usuario tiene permisos sobre esta cita
    if not verificar_propiedad_cita(cita_id, session['user_id'], session['rol']):
        flash('No tienes permisos para modificar esta cita', 'danger')
        return redirect(url_for('calendario'))
    
    with db_connection() as conn:
        try:
            # Obtener información actual de la cita
            cita_actual = conn.execute('''
                SELECT c.*, f.nombres_apellidos, u.usuario as profesional_usuario, u.nombre_completo as profesional_nombre
                FROM citas c
                JOIN familias f ON c.familia_id = f.id
                JOIN usuarios u ON c.profesional_id = u.id
                WHERE c.id = ?
            ''', (cita_id,)).fetchone()
            
            if not cita_actual:
                flash('Cita no encontrada', 'danger')
                return redirect(url_for('calendario'))
            
            # Validar que el profesional no puede marcar como atendida si no está autorizada
            if (session['rol'] == 'profesional' and 
                nuevo_estado == 'atendida' and 
                not cita_actual['cita_autorizada']):
                flash('No puede marcar la cita como atendida hasta que sea autorizada por administración', 'warning')
                return redirect(url_for('calendario'))
            
            # Actualizar estado
            conn.execute(
                "UPDATE citas SET estado = ?, notas = COALESCE(?, notas), fecha_actualizacion = datetime('now') WHERE id = ?",
                (nuevo_estado, notas, cita_id)
            )
            
            # Crear notificación según el cambio de estado
            mensajes_estado = {
                'confirmada': f"✅ Cita #{cita_id} confirmada con {cita_actual['nombres_apellidos']}",
                'cancelada': f"❌ Cita #{cita_id} cancelada con {cita_actual['nombres_apellidos']}",
                'atendida': f"🎉 Cita #{cita_id} marcada como atendida con {cita_actual['nombres_apellidos']}",
                'no_atendida': f"⚠️ Cita #{cita_id} marcada como no atendida con {cita_actual['nombres_apellidos']}"
            }
            
            if nuevo_estado in mensajes_estado:
                mensaje = mensajes_estado[nuevo_estado]
                
                # Notificar al profesional (si no fue él quien hizo el cambio)
                if session['usuario'] != cita_actual['profesional_usuario']:
                    crear_alerta_mejorada(cita_id, mensaje, usuario_destino=cita_actual['profesional_usuario'], tipo='info')
                
                # Notificar a coordinación/admin
                if session['rol'] != 'admin' and session['rol'] != 'coordinadora':
                    crear_alerta_mejorada(cita_id, f"{mensaje} por {session['nombre_completo']}", rol_destino='coordinadora', tipo='info')
            
            conn.commit()
            
            app.logger.info(f"Cita #{cita_id} actualizada a estado {nuevo_estado} por {session['usuario']}")
            flash(f'Estado de cita actualizado a {nuevo_estado}', 'success')
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error actualizando estado de cita: {e}")
            flash('Error al actualizar el estado de la cita', 'danger')
    
    return redirect(url_for('calendario'))

@app.route('/gestion_citas')
@verificar_sesion
def gestion_citas():
    vista = request.args.get('vista', 'pendientes')
    profesional_filtro = request.args.get('profesional', '')
    estado_filtro = request.args.get('estado', '')
    autorizacion_filtro = request.args.get('autorizacion', '')
    
    with db_connection() as conn:
        # Construir consulta base optimizada - CORREGIDA
        query = '''
            SELECT c.*, f.nombres_apellidos as familia_nombre, f.nombre_hijo_hija, f.telefono_principal,
                   f.direccion, f.email, f.tipo_identificacion, f.numero_identificacion,
                   u.nombre_completo as profesional_nombre, u.color_calendario
            FROM citas c
            JOIN familias f ON c.familia_id = f.id
            JOIN usuarios u ON c.profesional_id = u.id
            WHERE 1=1
        '''
        params = []
        
        # CORRECCIÓN: Aplicar filtros según vista MEJORADO
        if vista == 'pendientes':
            query += " AND c.estado IN ('agendada', 'confirmada')"
        elif vista == 'hoy':
            query += " AND date(c.fecha_hora) = date('now')"
        elif vista == 'semana':
            query += " AND date(c.fecha_hora) BETWEEN date('now') AND date('now', '+7 days')"
        elif vista == 'pasadas':
            query += " AND date(c.fecha_hora) < date('now')"
        elif vista == 'sin_autorizar':
            query += " AND c.cita_autorizada = 0 AND c.estado IN ('agendada', 'confirmada')"
        elif vista == 'autorizadas':
            query += " AND c.cita_autorizada = 1 AND c.estado IN ('agendada', 'confirmada')"
        
        # CORRECCIÓN: Filtro por profesional
        if profesional_filtro:
            query += " AND c.profesional_id = ?"
            params.append(profesional_filtro)
        elif session['rol'] == 'profesional':
            # Si es profesional, filtrar solo sus citas
            query += " AND c.profesional_id = ?"
            params.append(session['user_id'])
        
        # CORRECCIÓN: Filtro por estado
        if estado_filtro:
            query += " AND c.estado = ?"
            params.append(estado_filtro)
            
        # CORRECCIÓN: Filtro por autorización
        if autorizacion_filtro and session['rol'] in ['admin', 'administracion', 'coordinadora']:
            if autorizacion_filtro == 'autorizadas':
                query += " AND c.cita_autorizada = 1"
            elif autorizacion_filtro == 'pendientes':
                query += " AND c.cita_autorizada = 0 AND c.estado IN ('agendada', 'confirmada')"
        
        query += " ORDER BY c.fecha_hora DESC LIMIT 100"
        
        citas = conn.execute(query, params).fetchall()
        
        # Obtener profesionales para filtros
        profesionales = conn.execute(
            "SELECT id, nombre_completo FROM usuarios WHERE rol = 'profesional' AND activo = 1"
        ).fetchall()
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('gestion_citas.html',
                         citas=citas,
                         vista_actual=vista,
                         profesionales=profesionales,
                         profesional_filtro=profesional_filtro,
                         estado_filtro=estado_filtro,
                         autorizacion_filtro=autorizacion_filtro,
                         rol=session['rol'],
                         contadores=contadores)

# ===== NUEVA RUTA PARA OBTENER DETALLES DE FAMILIA POR ID DIRECTO =====
@app.route('/api/familias/<int:familia_id>')
@verificar_sesion
@requiere_rol(['admin', 'profesional', 'coordinadora'])
def obtener_familia_por_id(familia_id):
    """API para obtener detalles de familia por ID directo - NUEVA RUTA"""
    with db_connection() as conn:
        try:
            app.logger.info(f"🔍 Buscando familia por ID: #{familia_id}")
            
            # Obtener información de la familia
            familia = conn.execute('''
                SELECT 
                    id, nombres_apellidos, tipo_identificacion, numero_identificacion,
                    direccion, telefono_principal, telefono_secundario, email,
                    nombre_hijo_hija, fecha_nacimiento_hijo, edad_actual, notas,
                    fecha_creacion, activo
                FROM familias 
                WHERE id = ? AND activo = 1
            ''', (familia_id,)).fetchone()
            
            if not familia:
                app.logger.warning(f"❌ Familia #{familia_id} no encontrada o inactiva")
                return jsonify({
                    'error': 'Familia no encontrada o inactiva',
                    'status': 'error'
                }), 404
            
            app.logger.info(f"✅ Familia #{familia_id} encontrada: {familia['nombres_apellidos']}")
            
            # Obtener citas relacionadas con esta familia
            citas_recientes = conn.execute('''
                SELECT 
                    c.id, c.fecha_hora, c.estado, c.tipo_consulta,
                    u.nombre_completo as profesional_nombre
                FROM citas c
                LEFT JOIN usuarios u ON c.profesional_id = u.id
                WHERE c.familia_id = ?
                ORDER BY c.fecha_hora DESC
                LIMIT 10
            ''', (familia_id,)).fetchall()
            
            # Convertir a diccionario
            familia_data = dict(familia)
            
            # Formatear datos para mejor presentación
            if familia_data.get('fecha_nacimiento_hijo'):
                try:
                    # Mapeo de meses en español
                    meses_es = {
                        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
                        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
                        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
                    }
                    nacimiento = datetime.datetime.strptime(familia_data['fecha_nacimiento_hijo'], '%Y-%m-%d')
                    mes_es = meses_es[nacimiento.month]
                    familia_data['fecha_nacimiento_formateada'] = f"{nacimiento.day} de {mes_es}, {nacimiento.year}"
                except Exception as e:
                    app.logger.warning(f"⚠️ Error formateando fecha: {e}")
                    familia_data['fecha_nacimiento_formateada'] = familia_data['fecha_nacimiento_hijo']
            
            # Preparar respuesta
            response_data = {
                'familia': familia_data,
                'citas_recientes': [dict(cita) for cita in citas_recientes],
                'status': 'success'
            }
            
            app.logger.info(f"✅ Datos de familia preparados para ID #{familia_id}")
            return jsonify(response_data)
            
        except Exception as e:
            app.logger.error(f"❌ Error crítico obteniendo familia por ID #{familia_id}: {e}")
            return jsonify({
                'error': f'Error interno del servidor: {str(e)}',
                'status': 'error'
            }), 500

# ===== NUEVA RUTA PARA OBTENER FAMILIA POR CITA =====
@app.route('/api/familias/cita/<int:cita_id>')
@verificar_sesion
def obtener_familia_por_cita(cita_id):
    """API para obtener detalles de familia por ID de cita - CORREGIDA Y MEJORADA"""
    with db_connection() as conn:
        try:
            app.logger.info(f"🔍 Buscando familia para cita #{cita_id}")
            
            # Primero obtener información básica de la cita y el familia_id
            cita = conn.execute('''
                SELECT c.familia_id, f.nombres_apellidos, f.nombre_hijo_hija
                FROM citas c 
                LEFT JOIN familias f ON c.familia_id = f.id
                WHERE c.id = ?
            ''', (cita_id,)).fetchone()
            
            if not cita:
                app.logger.warning(f"❌ Cita #{cita_id} no encontrada")
                return jsonify({
                    'error': 'Cita no encontrada',
                    'status': 'error'
                }), 404
            
            familia_id = cita['familia_id']
            app.logger.info(f"✅ Cita #{cita_id} encontrada, familia_id: {familia_id}")
            
            if not familia_id:
                app.logger.warning(f"❌ Cita #{cita_id} no tiene familia_id asociado")
                return jsonify({
                    'error': 'La cita no tiene una familia asociada',
                    'status': 'error'
                }), 404
            
            # Ahora obtener los detalles completos de la familia
            familia = conn.execute('''
                SELECT 
                    id, nombres_apellidos, tipo_identificacion, numero_identificacion,
                    direccion, telefono_principal, telefono_secundario, email,
                    nombre_hijo_hija, fecha_nacimiento_hijo, edad_actual, notas,
                    fecha_creacion, activo
                FROM familias 
                WHERE id = ? AND activo = 1
            ''', (familia_id,)).fetchone()
            
            if not familia:
                app.logger.warning(f"❌ Familia #{familia_id} no encontrada o inactiva")
                return jsonify({
                    'error': 'Familia no encontrada o inactiva',
                    'status': 'error'
                }), 404
            
            app.logger.info(f"✅ Familia #{familia_id} encontrada: {familia['nombres_apellidos']}")
            
            # Obtener citas relacionadas con esta familia
            citas_recientes = conn.execute('''
                SELECT 
                    c.id, c.fecha_hora, c.estado, c.tipo_consulta,
                    u.nombre_completo as profesional_nombre
                FROM citas c
                LEFT JOIN usuarios u ON c.profesional_id = u.id
                WHERE c.familia_id = ?
                ORDER BY c.fecha_hora DESC
                LIMIT 10
            ''', (familia_id,)).fetchall()
            
            # Convertir a diccionario
            familia_data = dict(familia)
            
            # Formatear datos para mejor presentación
            if familia_data.get('fecha_nacimiento_hijo'):
                try:
                    # Mapeo de meses en español
                    meses_es = {
                        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
                        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
                        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
                    }
                    nacimiento = datetime.datetime.strptime(familia_data['fecha_nacimiento_hijo'], '%Y-%m-%d')
                    mes_es = meses_es[nacimiento.month]
                    familia_data['fecha_nacimiento_formateada'] = f"{nacimiento.day} de {mes_es}, {nacimiento.year}"
                except Exception as e:
                    app.logger.warning(f"⚠️ Error formateando fecha: {e}")
                    familia_data['fecha_nacimiento_formateada'] = familia_data['fecha_nacimiento_hijo']
            
            # Preparar respuesta
            response_data = {
                'familia': familia_data,
                'citas_recientes': [dict(cita) for cita in citas_recientes],
                'status': 'success'
            }
            
            app.logger.info(f"✅ Datos de familia preparados para cita #{cita_id}")
            return jsonify(response_data)
            
        except Exception as e:
            app.logger.error(f"❌ Error crítico obteniendo familia por cita #{cita_id}: {e}")
            return jsonify({
                'error': f'Error interno del servidor: {str(e)}',
                'status': 'error'
            }), 500

@app.route('/familias')
@verificar_sesion
@requiere_rol(['admin', 'profesional', 'coordinadora'])
def familias():
    buscar = sanitizar_input(request.args.get('buscar', ''))
    pagina = int(request.args.get('pagina', 1))
    por_pagina = 50
    
    with db_connection() as conn:
        offset = (pagina - 1) * por_pagina
        
        if buscar:
            # Búsqueda optimizada con parámetros preparados
            buscar_param = f"%{buscar}%"
            familias_data = conn.execute('''
                SELECT * FROM familias 
                WHERE (nombres_apellidos LIKE ? OR nombre_hijo_hija LIKE ? OR telefono_principal LIKE ? OR numero_identificacion LIKE ?)
                AND activo = 1
                ORDER BY nombres_apellidos
                LIMIT ? OFFSET ?
            ''', (buscar_param, buscar_param, buscar_param, buscar_param, por_pagina, offset)).fetchall()
            
            total = conn.execute('''
                SELECT COUNT(*) as c FROM familias 
                WHERE (nombres_apellidos LIKE ? OR nombre_hijo_hija LIKE ? OR telefono_principal LIKE ? OR numero_identificacion LIKE ?)
                AND activo = 1
            ''', (buscar_param, buscar_param, buscar_param, buscar_param)).fetchone()['c']
        else:
            familias_data = conn.execute('''
                SELECT * FROM familias 
                WHERE activo = 1 
                ORDER BY nombres_apellidos 
                LIMIT ? OFFSET ?
            ''', (por_pagina, offset)).fetchall()
            
            total = conn.execute(
                "SELECT COUNT(*) as c FROM familias WHERE activo = 1"
            ).fetchone()['c']
        
        total_paginas = (total + por_pagina - 1) // por_pagina
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('familias.html', 
                         familias=familias_data, 
                         buscar=buscar,
                         pagina=pagina,
                         total_paginas=total_paginas,
                         total_familias=total,
                         contadores=contadores)

@app.route('/familias/agregar', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin', 'profesional', 'coordinadora'])
def agregar_familia():
    datos = {
        'nombres_apellidos': sanitizar_input(request.form.get('nombres_apellidos', '')),
        'tipo_identificacion': sanitizar_input(request.form.get('tipo_identificacion', '')),
        'numero_identificacion': sanitizar_input(request.form.get('numero_identificacion', '')),
        'direccion': sanitizar_input(request.form.get('direccion', ''), 500),
        'telefono_principal': sanitizar_input(request.form.get('telefono_principal', '')),
        'telefono_secundario': sanitizar_input(request.form.get('telefono_secundario', '')),
        'email': sanitizar_input(request.form.get('email', '')).lower(),
        'nombre_hijo_hija': sanitizar_input(request.form.get('nombre_hijo_hija', '')),
        'fecha_nacimiento_hijo': request.form.get('fecha_nacimiento_hijo', '').strip(),
        'notas': sanitizar_input(request.form.get('notas', ''), 1000)
    }
    
    # Validaciones mejoradas
    campos_requeridos = ['nombres_apellidos', 'tipo_identificacion', 'numero_identificacion', 'telefono_principal', 'nombre_hijo_hija']
    for campo in campos_requeridos:
        if not datos[campo]:
            flash(f'El campo {campo.replace("_", " ").title()} es requerido', 'danger')
            return redirect(url_for('familias'))
    
    # Validar formato de teléfono
    if not validar_telefono(datos['telefono_principal']):
        flash('El teléfono principal debe contener solo números (10-15 dígitos)', 'danger')
        return redirect(url_for('familias'))
    
    # Validar email si se proporciona
    if datos['email'] and not validar_email(datos['email']):
        flash('El formato del email es inválido', 'danger')
        return redirect(url_for('familias'))
    
    with db_connection() as conn:
        try:
            # Verificar que no existe ya la identificación
            existente = conn.execute(
                "SELECT id FROM familias WHERE numero_identificacion = ?", 
                (datos['numero_identificacion'],)
            ).fetchone()
            
            if existente:
                flash('Ya existe una familia con ese número de identificación', 'danger')
                return redirect(url_for('familias'))
            
            # Calcular edad si se proporcionó fecha de nacimiento
            edad_actual = None
            if datos['fecha_nacimiento_hijo']:
                try:
                    nacimiento = datetime.datetime.strptime(datos['fecha_nacimiento_hijo'], '%Y-%m-%d')
                    hoy = datetime.datetime.now()
                    edad_actual = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
                except ValueError:
                    flash('Formato de fecha de nacimiento inválido', 'danger')
                    return redirect(url_for('familias'))
            
            # Insertar familia
            cursor = conn.execute('''
                INSERT INTO familias 
                (nombres_apellidos, tipo_identificacion, numero_identificacion, direccion,
                 telefono_principal, telefono_secundario, email, nombre_hijo_hija, 
                 fecha_nacimiento_hijo, edad_actual, notas)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                datos['nombres_apellidos'], datos['tipo_identificacion'], datos['numero_identificacion'], 
                datos['direccion'], datos['telefono_principal'], datos['telefono_secundario'], 
                datos['email'], datos['nombre_hijo_hija'], datos['fecha_nacimiento_hijo'], 
                edad_actual, datos['notas']
            ))
            
            familia_id = cursor.lastrowid
            
            # Crear alerta de nueva familia
            crear_alerta_mejorada(None, f"👨‍👩‍👧‍👦 Nueva familia registrada: {datos['nombres_apellidos']} - {datos['nombre_hijo_hija']}", rol_destino='coordinadora', tipo='info')
            
            conn.commit()
            
            app.logger.info(f"Familia #{familia_id} agregada por {session['usuario']}")
            flash('Familia agregada exitosamente', 'success')
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error agregando familia: {e}")
            flash('Error al agregar la familia', 'danger')
    
    return redirect(url_for('familias'))

@app.route('/autorizaciones')
@verificar_sesion
@requiere_rol(['admin', 'administracion', 'coordinadora'])
def autorizaciones():
    vista = request.args.get('vista', 'pendientes')
    familia_filtro = request.args.get('familia', '')
    profesional_filtro = request.args.get('profesional', '')
    pagina = int(request.args.get('pagina', 1))
    por_pagina = 50
    
    with db_connection() as conn:
        offset = (pagina - 1) * por_pagina
        
        query = '''
            SELECT c.*, f.nombres_apellidos, f.nombre_hijo_hija, f.telefono_principal,
                   f.direccion, f.email, f.tipo_identificacion, f.numero_identificacion,
                   u.nombre_completo as profesional_nombre, u.usuario as profesional_usuario
            FROM citas c
            JOIN familias f ON c.familia_id = f.id
            JOIN usuarios u ON c.profesional_id = u.id
            WHERE 1=1
        '''
        params = []
        
        # FILTROS MEJORADOS PARA AUTORIZACIONES
        if vista == 'pendientes':
            query += " AND c.cita_autorizada = 0 AND c.estado IN ('agendada', 'confirmada')"
        elif vista == 'autorizadas':
            query += " AND c.cita_autorizada = 1"
        elif vista == 'hoy':
            query += " AND date(c.fecha_creacion) = date('now')"
        elif vista == 'sin_autorizar':
            query += " AND c.cita_autorizada = 0 AND c.estado IN ('agendada', 'confirmada')"
        
        if familia_filtro:
            query += " AND (f.nombres_apellidos LIKE ? OR f.nombre_hijo_hija LIKE ?)"
            params.extend([f'%{familia_filtro}%', f'%{familia_filtro}%'])
            
        # NUEVO: Filtro por profesional
        if profesional_filtro:
            query += " AND c.profesional_id = ?"
            params.append(profesional_filtro)
        
        query += " ORDER BY c.fecha_creacion DESC LIMIT ? OFFSET ?"
        params.extend([por_pagina, offset])
        
        citas_data = conn.execute(query, params).fetchall()
        
        # Contar total para paginación
        count_query = '''
            SELECT COUNT(*) as c FROM citas c
            JOIN familias f ON c.familia_id = f.id
            WHERE 1=1
        '''
        count_params = []
        
        if vista == 'pendientes':
            count_query += " AND c.cita_autorizada = 0 AND c.estado IN ('agendada', 'confirmada')"
        elif vista == 'autorizadas':
            count_query += " AND c.cita_autorizada = 1"
        elif vista == 'hoy':
            count_query += " AND date(c.fecha_creacion) = date('now')"
        elif vista == 'sin_autorizar':
            count_query += " AND c.cita_autorizada = 0 AND c.estado IN ('agendada', 'confirmada')"
        
        if familia_filtro:
            count_query += " AND (f.nombres_apellidos LIKE ? OR f.nombre_hijo_hija LIKE ?)"
            count_params.extend([f'%{familia_filtro}%', f'%{familia_filtro}%'])
            
        if profesional_filtro:
            count_query += " AND c.profesional_id = ?"
            count_params.append(profesional_filtro)
        
        total = conn.execute(count_query, count_params).fetchone()['c']
        total_paginas = (total + por_pagina - 1) // por_pagina
        
        # Obtener familias para filtros (limitado para performance)
        familias = conn.execute(
            "SELECT id, nombres_apellidos, nombre_hijo_hija FROM familias WHERE activo = 1 ORDER BY nombres_apellidos LIMIT 100"
        ).fetchall()
        
        # Obtener profesionales para filtros
        profesionales = conn.execute(
            "SELECT id, nombre_completo FROM usuarios WHERE rol = 'profesional' AND activo = 1"
        ).fetchall()
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('autorizaciones.html',
                         citas=citas_data,
                         vista_actual=vista,
                         familias=familias,
                         profesionales=profesionales,
                         familia_filtro=familia_filtro,
                         profesional_filtro=profesional_filtro,
                         pagina=pagina,
                         total_paginas=total_paginas,
                         total_citas=total,
                         contadores=contadores)

@app.route('/reportes_citas')
@verificar_sesion
@requiere_rol(['admin', 'coordinadora'])
def reportes_citas():
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    profesional_id = request.args.get('profesional', '')
    estado = request.args.get('estado', '')
    tipo_consulta = request.args.get('tipo_consulta', '')
    
    with db_connection() as conn:
        query = '''
            SELECT c.*, f.nombres_apellidos, f.nombre_hijo_hija, f.telefono_principal,
                   f.direccion, f.email, f.tipo_identificacion, f.numero_identificacion,
                   u.nombre_completo as profesional_nombre, u.color_calendario
            FROM citas c
            JOIN familias f ON c.familia_id = f.id
            JOIN usuarios u ON c.profesional_id = u.id
            WHERE 1=1
        '''
        params = []
        
        if desde:
            query += " AND date(c.fecha_hora) >= date(?)"
            params.append(desde)
        
        if hasta:
            query += " AND date(c.fecha_hora) <= date(?)"
            params.append(hasta)
        
        if profesional_id:
            query += " AND c.profesional_id = ?"
            params.append(profesional_id)
        
        if estado:
            query += " AND c.estado = ?"
            params.append(estado)
        
        if tipo_consulta:
            query += " AND c.tipo_consulta = ?"
            params.append(tipo_consulta)
        
        query += " ORDER BY c.fecha_hora DESC LIMIT 200"
        
        citas = conn.execute(query, params).fetchall()
        
        # Obtener profesionales para filtros
        profesionales = conn.execute(
            "SELECT id, nombre_completo FROM usuarios WHERE rol = 'profesional' AND activo = 1"
        ).fetchall()
        
        # Estadísticas avanzadas
        stats_query = '''
            SELECT 
                COUNT(*) as total_citas,
                SUM(CASE WHEN estado = 'agendada' THEN 1 ELSE 0 END) as citas_agendadas,
                SUM(CASE WHEN estado = 'confirmada' THEN 1 ELSE 0 END) as citas_confirmadas,
                SUM(CASE WHEN estado = 'atendida' THEN 1 ELSE 0 END) as citas_atendidas,
                SUM(CASE WHEN estado = 'cancelada' THEN 1 ELSE 0 END) as citas_canceladas,
                SUM(CASE WHEN tipo_consulta = 'virtual' THEN 1 ELSE 0 END) as virtuales,
                SUM(CASE WHEN tipo_consulta = 'presencial' THEN 1 ELSE 0 END) as presenciales,
                SUM(CASE WHEN tipo_consulta = 'domicilio' THEN 1 ELSE 0 END) as domicilio,
                SUM(CASE WHEN cita_autorizada = 1 THEN 1 ELSE 0 END) as citas_autorizadas
            FROM citas c
            WHERE 1=1
        '''
        stats_params = []
        
        if desde:
            stats_query += " AND date(c.fecha_hora) >= date(?)"
            stats_params.append(desde)
        
        if hasta:
            stats_query += " AND date(c.fecha_hora) <= date(?)"
            stats_params.append(hasta)
        
        if profesional_id:
            stats_query += " AND c.profesional_id = ?"
            stats_params.append(profesional_id)
        
        if estado:
            stats_query += " AND c.estado = ?"
            stats_params.append(estado)
        
        stats = conn.execute(stats_query, stats_params).fetchone()
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('reportes_citas.html',
                         citas=citas,
                         stats=stats,
                         profesionales=profesionales,
                         desde_filtro=desde,
                         hasta_filtro=hasta,
                         profesional_filtro=profesional_id,
                         estado_filtro=estado,
                         tipo_consulta_filtro=tipo_consulta,
                         contadores=contadores)

@app.route('/alertas')
@verificar_sesion
def alertas():
    with db_connection() as conn:
        alertas_data = obtener_alertas_no_leidas(session['usuario'], session['rol'])
        
        # Obtener contadores específicos
        contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
        
        return render_template('alertas.html', 
                             alertas=alertas_data,
                             contadores=contadores)

@app.route('/alertas/marcar_leida/<int:alerta_id>', methods=['POST'])
@verificar_sesion
def marcar_alerta_leida(alerta_id):
    with db_connection() as conn:
        try:
            conn.execute(
                "UPDATE alertas SET leida = 1, fecha_leida = datetime('now') WHERE id = ?",
                (alerta_id,)
            )
            conn.commit()
            
            # Actualizar contador en tiempo real
            if 'usuario' in session:
                socketio.emit('actualizar_contador', {}, room=f"user_{session['usuario']}")
                socketio.emit('actualizar_contador', {}, room=f"rol_{session['rol']}")
            
            flash('Alerta marcada como leída', 'info')
        except Exception as e:
            app.logger.error(f"Error marcando alerta como leída: {e}")
            flash('Error al marcar la alerta como leída', 'danger')
    
    return redirect(url_for('alertas'))

@app.route('/alertas/marcar_todas_leidas', methods=['POST'])
@verificar_sesion
def marcar_todas_leidas():
    with db_connection() as conn:
        try:
            if session['rol'] in ['admin', 'coordinadora']:
                conn.execute(
                    "UPDATE alertas SET leida = 1, fecha_leida = datetime('now') WHERE (usuario_destino IS NULL OR usuario_destino = ?) AND leida = 0",
                    (session['usuario'],)
                )
            else:
                conn.execute(
                    "UPDATE alertas SET leida = 1, fecha_leida = datetime('now') WHERE usuario_destino = ? AND leida = 0",
                    (session['usuario'],)
                )
            conn.commit()
            
            # Actualizar contador en tiempo real
            if 'usuario' in session:
                socketio.emit('actualizar_contador', {}, room=f"user_{session['usuario']}")
                socketio.emit('actualizar_contador', {}, room=f"rol_{session['rol']}")
            
            flash('Todas las alertas marcadas como leídas', 'info')
        except Exception as e:
            app.logger.error(f"Error marcando todas las alertas como leídas: {e}")
            flash('Error al marcar las alertas como leídas', 'danger')
    
    return redirect(url_for('alertas'))

@app.route('/usuarios')
@verificar_sesion
@requiere_rol(['admin'])
def usuarios():
    with db_connection() as conn:
        usuarios_data = conn.execute('''
            SELECT u.*, 
                   (SELECT COUNT(*) FROM citas WHERE profesional_id = u.id) as total_citas,
                   (SELECT COUNT(*) FROM citas WHERE profesional_id = u.id AND date(fecha_hora) >= date('now')) as citas_futuras
            FROM usuarios u 
            ORDER BY u.rol, u.nombre_completo
        ''').fetchall()
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('usuarios.html', 
                         usuarios=usuarios_data,
                         contadores=contadores)

# ===== RUTAS COMPLETAS DE GESTIÓN DE USUARIOS - CORREGIDAS Y EXPANDIDAS =====

@app.route('/usuarios/crear', methods=['GET', 'POST'])
@verificar_sesion
@requiere_rol(['admin'])
def usuarios_crear():
    """Crear nuevo usuario - RUTA NUEVA"""
    if request.method == 'POST':
        usuario = sanitizar_input(request.form.get('usuario', ''))
        contrasena = request.form.get('contrasena', '')
        rol = request.form.get('rol', '')
        nombre_completo = sanitizar_input(request.form.get('nombre_completo', ''))
        color_calendario = request.form.get('color_calendario', '#3498db')
        
        # Validaciones
        if not all([usuario, contrasena, rol, nombre_completo]):
            flash('Todos los campos marcados con * son requeridos', 'danger')
            return redirect(url_for('usuarios_crear'))
        
        if len(contrasena) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'danger')
            return redirect(url_for('usuarios_crear'))
        
        # CORRECCIÓN: Usar re.match en lugar de sintaxis JavaScript
        if not re.match(r'^[a-zA-Z0-9_]+$', usuario):
            flash('El usuario solo puede contener letras, números y guiones bajos (sin espacios)', 'danger')
            return redirect(url_for('usuarios_crear'))
        
        with db_connection() as conn:
            try:
                # Verificar si el usuario ya existe
                existente = conn.execute(
                    "SELECT id FROM usuarios WHERE usuario = ?", 
                    (usuario,)
                ).fetchone()
                
                if existente:
                    flash('Ya existe un usuario con ese nombre de usuario', 'danger')
                    return redirect(url_for('usuarios_crear'))
                
                # Crear nuevo usuario
                conn.execute(
                    "INSERT INTO usuarios (usuario, contrasena, rol, nombre_completo, color_calendario) VALUES (?,?,?,?,?)",
                    (usuario, generate_password_hash(contrasena), rol, nombre_completo, color_calendario)
                )
                conn.commit()
                
                app.logger.info(f"Usuario {usuario} creado por {session['usuario']}")
                flash(f'Usuario {usuario} creado exitosamente', 'success')
                return redirect(url_for('usuarios'))
                
            except Exception as e:
                conn.rollback()
                app.logger.error(f"Error creando usuario: {e}")
                flash('Error al crear el usuario', 'danger')
                return redirect(url_for('usuarios_crear'))
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('crear_usuario.html', contadores=contadores)

@app.route('/usuarios/editar/<string:username>', methods=['GET', 'POST'])
@verificar_sesion
@requiere_rol(['admin'])
def usuarios_editar(username):
    """Editar usuario existente - RUTA MEJORADA"""
    with db_connection() as conn:
        if request.method == 'POST':
            nuevo_rol = request.form.get('rol', '')
            nuevo_nombre_completo = sanitizar_input(request.form.get('nombre_completo', ''))
            nuevo_color = request.form.get('color_calendario', '#3498db')
            nueva_contrasena = request.form.get('contrasena', '')
            nuevo_activo = request.form.get('activo', '0') == '1'
            
            try:
                if nueva_contrasena:
                    # Validar fortaleza de contraseña
                    if len(nueva_contrasena) < 6:
                        flash('La contraseña debe tener al menos 6 caracteres', 'danger')
                        return redirect(url_for('usuarios_editar', username=username))
                    
                    conn.execute(
                        "UPDATE usuarios SET rol = ?, nombre_completo = ?, color_calendario = ?, contrasena = ?, activo = ? WHERE usuario = ?",
                        (nuevo_rol, nuevo_nombre_completo, nuevo_color, generate_password_hash(nueva_contrasena), nuevo_activo, username)
                    )
                    flash(f'Usuario {username} actualizado con nueva contraseña', 'success')
                else:
                    conn.execute(
                        "UPDATE usuarios SET rol = ?, nombre_completo = ?, color_calendario = ?, activo = ? WHERE usuario = ?",
                        (nuevo_rol, nuevo_nombre_completo, nuevo_color, nuevo_activo, username)
                    )
                    flash(f'Usuario {username} actualizado exitosamente', 'success')
                
                conn.commit()
                app.logger.info(f"Usuario {username} actualizado por {session['usuario']}")
                
                return redirect(url_for('usuarios'))
                
            except Exception as e:
                conn.rollback()
                app.logger.error(f"Error al actualizar usuario: {e}")
                flash(f'Error al actualizar usuario: {str(e)}', 'danger')
        
        usuario = conn.execute(
            "SELECT usuario, rol, nombre_completo, color_calendario, activo FROM usuarios WHERE usuario = ?", 
            (username,)
        ).fetchone()
    
    if not usuario:
        flash('Usuario no encontrado', 'danger')
        return redirect(url_for('usuarios'))
    
    # Obtener contadores específicos
    contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
    
    return render_template('editar_usuario.html', 
                         usuario=usuario,
                         contadores=contadores)

@app.route('/usuarios/restablecer/<string:username>', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin'])
def usuarios_restablecer(username):
    """Restablecer contraseña de usuario - RUTA CORREGIDA"""
    with db_connection() as conn:
        try:
            # Verificar que el usuario existe
            usuario_existente = conn.execute(
                "SELECT usuario FROM usuarios WHERE usuario = ?", 
                (username,)
            ).fetchone()
            
            if not usuario_existente:
                flash('Usuario no encontrado', 'danger')
                return redirect(url_for('usuarios'))
            
            # Restablecer contraseña
            contrasena_por_defecto = "NuevaContraseña123!"
            conn.execute(
                "UPDATE usuarios SET contrasena = ? WHERE usuario = ?",
                (generate_password_hash(contrasena_por_defecto), username)
            )
            conn.commit()
            
            app.logger.info(f"Contraseña de {username} restablecida por {session['usuario']}")
            flash(f'Contraseña de {username} restablecida exitosamente', 'success')
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error al restablecer contraseña: {e}")
            flash(f'Error al restablecer contraseña: {str(e)}', 'danger')
    
    return redirect(url_for('usuarios'))

# ===== RUTA CORREGIDA: USUARIOS ELIMINAR =====
@app.route('/usuarios/eliminar/<username>', methods=['POST'])
@verificar_sesion
@requiere_rol(['admin'])
def usuarios_eliminar(username):
    """Eliminar usuario del sistema - CORREGIDA"""
    with db_connection() as conn:
        try:
            # Verificar si el usuario existe
            usuario_existente = conn.execute(
                "SELECT * FROM usuarios WHERE usuario = ?",
                (username,)
            ).fetchone()

            if not usuario_existente:
                flash("❌ El usuario no existe.", "danger")
                return redirect(url_for('usuarios'))

            # No permitir eliminar el propio usuario
            if username == session['usuario']:
                flash("❌ No puedes eliminar tu propio usuario.", "danger")
                return redirect(url_for('usuarios'))

            # ---------------------------------------------------------
            # VERIFICACIÓN MEJORADA DE CITAS ACTIVAS
            # ---------------------------------------------------------
            # Solo bloquear si el usuario tiene citas FUTURAS
            citas_futuras = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM citas
                WHERE (profesional_id = ? OR usuario_creador = ?)
                  AND date(fecha_hora) >= date('now')
                  AND estado NOT IN ('cancelada', 'atendida', 'no_atendida')
                """,
                (usuario_existente['id'], usuario_existente['usuario'])
            ).fetchone()['c']

            if citas_futuras > 0:
                flash(
                    f"❌ No se puede eliminar el usuario {username}: tiene {citas_futuras} cita(s) futura(s). "
                    "Reasigna o cancela esas citas primero.",
                    'danger'
                )
                return redirect(url_for('usuarios'))

            # ---------------------------------------------------------
            # PROTEGER ÚLTIMO ADMINISTRADOR
            # ---------------------------------------------------------
            if usuario_existente['rol'] == "admin":
                admins = conn.execute(
                    "SELECT COUNT(*) AS c FROM usuarios WHERE rol = 'admin' AND activo = 1"
                ).fetchone()['c']

                if admins <= 1:
                    flash("❌ No se puede eliminar el último administrador activo.", "danger")
                    return redirect(url_for('usuarios'))

            # ---------------------------------------------------------
            # ELIMINAR USUARIO
            # ---------------------------------------------------------
            conn.execute("DELETE FROM usuarios WHERE usuario = ?", (username,))
            conn.commit()
            
            app.logger.info(f"Usuario {username} eliminado por {session['usuario']}")
            flash("✅ Usuario eliminado correctamente.", "success")

        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error al eliminar usuario: {e}")
            flash(f"❌ Error al eliminar usuario: {e}", "danger")

    return redirect(url_for('usuarios'))

# ===== NUEVAS APIS PARA NOTIFICACIONES MEJORADAS =====
@app.route('/api/alertas/count')
@verificar_sesion
def api_alertas_count():
    """API optimizada para obtener contador de alertas no leídas"""
    try:
        alertas_no_leidas = obtener_alertas_no_leidas(session['usuario'], session['rol'])
        count = len(alertas_no_leidas)
        badge_class = obtener_clase_badge(count)
        
        return jsonify({
            'count': count,
            'badge_class': badge_class,
            'status': 'success'
        })
    except Exception as e:
        app.logger.error(f"Error en api_alertas_count: {e}")
        return jsonify({
            'count': 0,
            'badge_class': '',
            'status': 'error',
            'message': 'Error obteniendo contador'
        }), 500

@app.route('/api/notificaciones/contadores_especificos')
@verificar_sesion
def api_contadores_especificos():
    """API para obtener contadores específicos por sección"""
    try:
        contadores = obtener_contadores_especificos(session['usuario'], session['rol'])
        
        return jsonify({
            'contadores': contadores,
            'status': 'success'
        })
    except Exception as e:
        app.logger.error(f"Error en api_contadores_especificos: {e}")
        return jsonify({
            'contadores': {},
            'status': 'error',
            'message': 'Error obteniendo contadores'
        }), 500

@app.route('/api/estadisticas/dashboard')
@verificar_sesion
def api_estadisticas_dashboard():
    """API para estadísticas del dashboard"""
    try:
        with db_connection() as conn:
            stats = {}
            
            if session['rol'] in ['admin', 'coordinadora']:
                stats = conn.execute('''
                    SELECT 
                        (SELECT COUNT(*) FROM citas) as total_citas,
                        (SELECT COUNT(*) FROM citas WHERE date(fecha_hora) = date('now')) as citas_hoy,
                        (SELECT COUNT(*) FROM citas WHERE estado IN ('agendada', 'confirmada')) as citas_pendientes,
                        (SELECT COUNT(*) FROM familias WHERE activo = 1) as total_familias,
                        (SELECT COUNT(*) FROM citas WHERE cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')) as citas_sin_autorizar
                ''').fetchone()
            
            elif session['rol'] == 'profesional':
                stats = conn.execute('''
                    SELECT 
                        (SELECT COUNT(*) FROM citas WHERE profesional_id = ? AND date(fecha_hora) = date('now')) as mis_citas_hoy,
                        (SELECT COUNT(*) FROM citas WHERE profesional_id = ? AND estado IN ('agendada', 'confirmada')) as mis_citas_pendientes,
                        (SELECT COUNT(*) FROM citas WHERE profesional_id = ? AND estado = 'confirmada') as mis_citas_confirmadas,
                        (SELECT COUNT(*) FROM citas WHERE profesional_id = ? AND date(fecha_hora) BETWEEN date('now') AND date('now', '+7 days')) as mis_citas_semana,
                        (SELECT COUNT(*) FROM citas WHERE profesional_id = ? AND cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')) as mis_citas_sin_autorizar
                ''', (session['user_id'], session['user_id'], session['user_id'], session['user_id'], session['user_id'])).fetchone()
            
            elif session['rol'] == 'administracion':
                stats = conn.execute('''
                    SELECT 
                        (SELECT COUNT(*) FROM citas WHERE cita_autorizada = 0 AND estado IN ('agendada', 'confirmada')) as citas_sin_autorizar,
                        (SELECT COUNT(*) FROM citas WHERE cita_autorizada = 1 AND date(fecha_actualizacion) = date('now')) as citas_autorizadas_hoy,
                        (SELECT COUNT(*) FROM citas WHERE estado IN ('agendada', 'confirmada')) as total_citas_pendientes
                ''').fetchone()
            
            return jsonify({
                'stats': dict(stats),
                'status': 'success'
            })
            
    except Exception as e:
        app.logger.error(f"Error en api_estadisticas_dashboard: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Error obteniendo estadísticas'
        }), 500

# ===== MANEJO DE ERRORES MEJORADO =====
@app.errorhandler(404)
def pagina_no_encontrada(e):
    app.logger.warning(f"Página no encontrada: {request.url} - Usuario: {session.get('usuario', 'No autenticado')}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Página no encontrada', 'status': 404}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def error_servidor(e):
    app.logger.error(f'Error 500: {e} - URL: {request.url} - Usuario: {session.get("usuario", "No autenticado")}')
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Error interno del servidor', 'status': 500}), 500
    return render_template('500.html'), 500

@app.errorhandler(403)
def acceso_denegado(e):
    app.logger.warning(f"Acceso denegado: {request.url} - Usuario: {session.get('usuario', 'No autenticado')} - Rol: {session.get('rol', 'No identificado')}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Acceso denegado', 'status': 403}), 403
    return render_template('403.html'), 403

# ===== INICIALIZACIÓN MEJORADA =====
def inicializar_sistema():
    """Inicializar el sistema completo con verificación"""
    try:
        app.logger.info("🚀 Iniciando Sistema de Gestión de Citas...")
        
        # Verificar si la base de datos existe
        if not os.path.exists(APP_DB):
            app.logger.info("📦 Creando base de datos optimizada...")
            init_db()
            crear_usuarios_iniciales()
            crear_familias_prueba()
            app.logger.info("✅ Sistema inicializado exitosamente")
        else:
            app.logger.info("✅ Base de datos existente detectada")
            
            # Verificar integridad de la base de datos
            with db_connection() as conn:
                try:
                    conn.execute("SELECT 1 FROM usuarios LIMIT 1")
                    app.logger.info("✅ Base de datos verificada correctamente")
                    
                    # Ejecutar migración
                    migrar_base_datos()
                    
                    # Reparar base de datos (agregar columnas faltantes)
                    reparar_base_datos()
                    
                except Exception as e:
                    app.logger.error(f"❌ Error en base de datos: {e}")
                    # Recrear la base de datos si hay errores
                    os.remove(APP_DB)
                    init_db()
                    crear_usuarios_iniciales()
                    crear_familias_prueba()
                    app.logger.info("✅ Base de datos recreada exitosamente")
        
        # Optimizar base de datos al inicio
        with db_connection() as conn:
            conn.execute("PRAGMA optimize")
            conn.execute("PRAGMA incremental_vacuum")
        
        app.logger.info("🎯 Sistema listo para recibir conexiones")
        
    except Exception as e:
        app.logger.error(f"❌ Error crítico en inicialización: {e}")
        raise e

# ===== EJECUCIÓN PRINCIPAL =====
if __name__ == '__main__':
    inicializar_sistema()
    
    # Configuración de servidor de producción
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    debug = app.config['DEBUG']
    
    app.logger.info(f"🌐 Servidor iniciando en {host}:{port} (Debug: {debug})")
    
    socketio.run(
        app, 
        host=host, 
        port=port, 
        debug=debug,
        allow_unsafe_werkzeug=True,
        log_output=True
    )
