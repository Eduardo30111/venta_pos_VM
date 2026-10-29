import sys

def trace_calls(frame, event, arg):
    if event == 'call' and 'inicio_sesion.py' in frame.f_code.co_filename:
        print(f"Llamando a: {frame.f_code.co_name}")
    elif event == 'line' and 'inicio_sesion.py' in frame.f_code.co_filename:
        pass # print(f"Linea {frame.f_lineno}")
    return trace_calls

sys.settrace(trace_calls)

try:
    with open("interface/inicio_sesion.py") as f:
        exec(f.read())
except Exception as e:
    print(f"ERROR FATAL ATRAPADO: {e}")
