import os
from YOLOv8 import anonymize


# class Process:
def start_process(**kwargs):
    print('Process started for media: ' + '...')
    model = anonymize.Anonymize()
    anonymize.Anonymize.load_model(model)
    anonymize.Anonymize.predict(model, **kwargs)


def stop_process():
    # os.killpg(os.getpid(), signal.SIGTERM)
    print('Process stopped')
