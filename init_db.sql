CREATE DATABASE IF NOT EXISTS zenix_os;
USE zenix_os;

CREATE TABLE IF NOT EXISTS tareas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    titulo VARCHAR(255) NOT NULL,
    descripcion TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    estado VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS alertas_programadas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tarea_id INT NULL,
    hora_ejecucion TIME NOT NULL,
    tipo_alerta VARCHAR(100) NOT NULL,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_alerta_tarea FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO alertas_programadas (tarea_id, hora_ejecucion, tipo_alerta)
SELECT NULL, '07:00:00', 'Despertar'
WHERE NOT EXISTS (
    SELECT 1 FROM alertas_programadas WHERE hora_ejecucion = '07:00:00' AND tipo_alerta = 'Despertar'
);

INSERT INTO alertas_programadas (tarea_id, hora_ejecucion, tipo_alerta)
SELECT NULL, '15:00:00', 'Recordatorio_Critico'
WHERE NOT EXISTS (
    SELECT 1 FROM alertas_programadas WHERE hora_ejecucion = '15:00:00' AND tipo_alerta = 'Recordatorio_Critico'
);
