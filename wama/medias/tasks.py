import os
import anonymizer.anonymize

from anonymizer import anonymize


# class Process:
def start_process(**kwargs):
    print('Process started for media: ' + str(kwargs['media_path']) + '...')
    model = anonymize.Anonymize()
    anonymize.Anonymize.load_model(model, **kwargs)
    anonymize.Anonymize.process(model, **kwargs)


def stop_process():
    # anonymizer.anonymize.stop_process()
    print('Process stopped')
