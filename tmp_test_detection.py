from core.artifacts import detect_artifact_request
from core.command_handler import detect_action_request

samples = [
    'crear tarea comprar leche',
    'crear un documento sobre historia',
    'genera un archivo html para mi pagina',
    'añade tarea llamar a mama a las 7 am'
]

for t in samples:
    print('INPUT:', t)
    print(' artifact:', detect_artifact_request(t))
    print(' action :', detect_action_request(t))
    print('---')
