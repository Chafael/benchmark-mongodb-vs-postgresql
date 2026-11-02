# Evidencia de spill, OOM y errores

Este archivo lista las corridas que no terminaron con estado `ok`. Cada una tiene su log completo en `logs/`. Los planes de ejecución que muestran el spill de Q1 en PostgreSQL ("Sort Method: external merge Disk") están en `logs/planes/`.

En MongoDB ninguna de las 81 corridas tuvo spill, OOM ni errores.

## Spill a disco (PostgreSQL, Q1)

Detectado por el aumento de `temp_files` y `temp_bytes` en `pg_stat_database` durante la ventana de medición.

- `postgresql_PROFILE_A_BASELINE_Q1_c10_r1.json`: 54 archivos temporales, 8.4 GB escritos, 16 consultas completadas
- `postgresql_PROFILE_A_BASELINE_Q1_c10_r2.json`: 54 archivos temporales, 8.7 GB escritos, 17 consultas completadas
- `postgresql_PROFILE_A_BASELINE_Q1_c10_r3.json`: 45 archivos temporales, 7.8 GB escritos, 14 consultas completadas
- `postgresql_PROFILE_A_BASELINE_Q1_c1_r1.json`: 456 archivos temporales, 49.2 GB escritos, 151 consultas completadas
- `postgresql_PROFILE_A_BASELINE_Q1_c1_r2.json`: 468 archivos temporales, 50.5 GB escritos, 156 consultas completadas
- `postgresql_PROFILE_A_BASELINE_Q1_c1_r3.json`: 471 archivos temporales, 50.8 GB escritos, 156 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c10_r1.json`: 43 archivos temporales, 7.4 GB escritos, 20 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c10_r2.json`: 51 archivos temporales, 9.7 GB escritos, 20 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c10_r3.json`: 40 archivos temporales, 8.4 GB escritos, 16 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c1_r1.json`: 98 archivos temporales, 10.6 GB escritos, 32 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c1_r2.json`: 55 archivos temporales, 5.9 GB escritos, 18 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c1_r3.json`: 128 archivos temporales, 13.8 GB escritos, 42 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c50_r1.json`: 18 archivos temporales, 2.9 GB escritos, 4 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c50_r2.json`: 15 archivos temporales, 1.7 GB escritos, 4 consultas completadas
- `postgresql_PROFILE_B_MEDIUM_Q1_c50_r3.json`: 11 archivos temporales, 1.3 GB escritos, 4 consultas completadas
- `postgresql_PROFILE_C_SEVERE_Q1_c10_r1.json`: 26 archivos temporales, 4.2 GB escritos, 3 consultas completadas
- `postgresql_PROFILE_C_SEVERE_Q1_c10_r2.json`: 43 archivos temporales, 7.4 GB escritos, 13 consultas completadas
- `postgresql_PROFILE_C_SEVERE_Q1_c10_r3.json`: 45 archivos temporales, 7.8 GB escritos, 14 consultas completadas
- `postgresql_PROFILE_C_SEVERE_Q1_c1_r1.json`: 72 archivos temporales, 7.8 GB escritos, 23 consultas completadas
- `postgresql_PROFILE_C_SEVERE_Q1_c1_r2.json`: 69 archivos temporales, 7.4 GB escritos, 22 consultas completadas
- `postgresql_PROFILE_C_SEVERE_Q1_c1_r3.json`: 54 archivos temporales, 5.8 GB escritos, 17 consultas completadas

## OOM (PostgreSQL, perfil C, Q1, 50 clientes)

Detectado con `docker inspect` (`State.OOMKilled = true`). El kernel mató procesos de PostgreSQL al rebasar el límite de 1 GB; las consultas en curso se perdieron.

- `postgresql_PROFILE_C_SEVERE_Q1_c50_r1.json`: OOMKilled=True, 704 errores, RSS máximo 908.4 MB, ejemplo: OperationalError: consuming input failed: server closed the connection unexpectedly
- `postgresql_PROFILE_C_SEVERE_Q1_c50_r2.json`: OOMKilled=True, 1176 errores, RSS máximo 950.3 MB, ejemplo: OperationalError: consuming input failed: server closed the connection unexpectedly
- `postgresql_PROFILE_C_SEVERE_Q1_c50_r3.json`: OOMKilled=True, 736 errores, RSS máximo 959.1 MB, ejemplo: OperationalError: consuming input failed: server closed the connection unexpectedly

## Error de memoria compartida (PostgreSQL, perfil A, Q1, 50 clientes)

No es un OOM del perfil: se llenó `/dev/shm`, que Docker limita a 64 MB por defecto y que PostgreSQL usa para comunicar los workers paralelos. En el perfil B con 50 clientes aparece el mismo error en parte de las consultas, aunque algunas sí terminaron.

- `postgresql_PROFILE_A_BASELINE_Q1_c50_r1.json`: 27668 errores, ejemplo: DiskFull: could not resize shared memory segment "/PostgreSQL.129617444" to 196736 bytes: No space left on device
- `postgresql_PROFILE_A_BASELINE_Q1_c50_r2.json`: 24393 errores, ejemplo: DiskFull: could not resize shared memory segment "/PostgreSQL.272279080" to 196736 bytes: No space left on device
- `postgresql_PROFILE_A_BASELINE_Q1_c50_r3.json`: 27258 errores, ejemplo: DiskFull: could not resize shared memory segment "/PostgreSQL.803870526" to 196736 bytes: No space left on device
