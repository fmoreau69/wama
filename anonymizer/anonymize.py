import os
import gc
import cv2
import torch
from pathlib import Path

from ultralytics import YOLO, settings
from ultralytics.utils import MACOS, WINDOWS
from ultralytics.engine.predictor import BasePredictor
# from anonymizer.blurrer import *
# from anonymizer.custom_yolo_model import YOLO
# from anonymizer.custom_model import Model
# from anonymizer.custom_predictor import BasePredictor

# Directories #######################################################
MAIN_DIR = os.path.dirname(os.getcwd())
DATASET_DIR = os.path.dirname(os.path.dirname(MAIN_DIR))

# Datasets
dataset_directory_faces_plates = os.path.join(DATASET_DIR, "DATASETS\FACES&PLATES\Faces&plates_test_new\data.yaml")
dataset_directory_faces = os.path.join(DATASET_DIR, "DATASETS\FACES\Face Detection.v21-yolov5s.yolov8\data.yaml")
dataset_directory_faces_merged = os.path.join(DATASET_DIR, "DATASETS\FACES\FACES_MERGED_OK\data.yaml")
dataset_directory_carLP = os.path.join(DATASET_DIR, "DATASETS\CAR_LICENCE_PLATES\Lisence_plate.v3i.yolov8_CarLP_640px\data.yaml")

# Models ############################################################
# Global Models #######################
coco_model_path = "models/yolov8n.pt"

# Faces&Plates Models #######################
faces_plates_model_path = "models/yolov8m_faces&plates_720p.pt"
# faces_plates_model_path = "models/yolov8m_faces&plates_1080p.pt"
# faces_plates_model_path = "models/yolov8n_faces&plates.pt"

train = False  # False


class Anonymize:
    def __init__(self):
        if torch.cuda.is_available():
            self.device = torch.cuda.device_count()
            print(f"Using {torch.cuda.get_device_name(torch.cuda.current_device())}.")
        else:
            self.device = "cpu"
            print("Using CPU.")
        self.source = os.path.join(MAIN_DIR, 'media/input_media')
        self.input_media_path = None
        self.destination = os.path.join(MAIN_DIR, 'media/output_media')
        self.output_media_path = None
        self.save_path = os.path.join(MAIN_DIR, 'anonymizer/runs')
        settings.update({'runs_dir': self.save_path, 'weights_dir': './weights'})
        self.model = None
        self.tracker = None
        self.mode = 'vid'
        self.vid_writer = None
        self.results = None
        self.plotted_img = None
        # Default settings
        self.classes2blur = ['face', 'plate']
        # self.classes2blur = ['person', 'car', 'truck', 'bus']
        self.model_path = coco_model_path
        if any([classe in self.classes2blur for classe in ['face', 'plate']]):
            self.model_path = faces_plates_model_path
        self.blur_ratio = 0.20
        self.ROI_enlargement = 0.50
        self.conf = 0.25
        self.blur = True
        self.show = True
        self.line_width = None
        self.boxes = True
        self.show_labels = True
        self.show_conf = True
        self.save = True
        self.save_txt = True

    def train_model(self):
        # self.model = YOLO("yolov8n.yaml")  # build a new model from scratch
        # self.model = YOLO("./weights/yolov8n.pt")  # load a pretrained model (recommended for training)
        self.model = YOLO(self.model_path)  # load a pretrained model (recommended for training)
        # self.model.to('cuda')
        # results = self.model.train(data="coco128.yaml", epochs=3)  # train the model
        # device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        results = self.model.train(data=dataset_directory_faces_merged, epochs=1, batch=32, device=0,
                                   name='yolov8n_faces&plates_test')  # train the model | **kwargs: ,imgsz=640
        results = self.model.val()  # evaluate model performance on the validation set

    def load_model(self):
        if self.model_path.endswith('.onnx'):
            self.model = YOLO(self.model_path)
            # onnx_model = onnx.load(self.model_path)
            # onnx_model = ConvertModel(onnx_model)
            # self.model = YOLO("./weights/Faces&Plates/yolov8m_faces&plates_720p.pt").load(onnx_model)
            # self.model = YOLO("./weights/yolov8n.pt").load(onnx_model)
        else:
            print('Model used: ' + self.model_path)
            self.model = YOLO(self.model_path)
            # self.model = YOLO("./weights/Faces&Plates/yolov8m_faces&plates_720p.pt").load(self.model_path)
            # self.model = InceptionResnetV1(pretrained=self.model_path)
            # self.model = tf.saved_model.load(self.model_path)

    def predict(self, **kwargs):
        self.model = YOLO(self.model_path)
        if os.path.isdir(self.source):
            for media in os.listdir(self.source):
                self.input_media_path = os.path.join(self.source, media)
                self.output_media_path = os.path.join(self.destination, media)
                Anonymize.apply_predict(self, **kwargs)
        else:
            self.input_media_path = self.source
            self.output_media_path = self.destination
            Anonymize.apply_predict(self, **kwargs)

    def track(self, **kwargs):
        self.model = YOLO(self.model_path)
        if os.path.isdir(self.source):
            for media in os.listdir(self.source):
                self.input_media_path = os.path.join(self.source, media)
                self.output_media_path = os.path.join(self.destination, media)
                Anonymize.apply_track(self, **kwargs)
        else:
            self.input_media_path = self.source
            self.output_media_path = self.destination
            Anonymize.apply_track(self, **kwargs)

    def apply_predict(self, **kwargs):
        # Get media width
        if self.mode == 'image':
            media = cv2.imread(self.input_media_path)
        else:
            media = cv2.VideoCapture(self.input_media_path)
            self.vid_writer = dict.fromkeys(range(int(media.get(cv2.CAP_PROP_FRAME_COUNT))))
        width = int(media.get(cv2.CAP_PROP_FRAME_WIDTH))

        # Apply model
        self.results = self.model.predict(
            source=self.input_media_path,
            # stream=True,
            task='detect',
            # mode='track',
            device=self.device,
            imgsz=width,
            save=self.save,
            save_txt=self.save_txt,
            # classes2blur=(kwargs['classes2blur'] if 'classes2blur' in kwargs else self.classes2blur),
            # blur_ratio=(kwargs['blur_ratio'] if 'blur_ratio' in kwargs else self.blur_ratio),
            # ROI_enlargement=(kwargs['ROI_enlargement'] if 'ROI_enlargement' in kwargs else self.ROI_enlargement),
            conf=(kwargs['detection_threshold'] if 'detection_threshold' in kwargs else self.conf),
            show=(kwargs['show_preview'] if 'show_preview' in kwargs else self.show),
            boxes=(kwargs['show_boxes'] if 'show_boxes' in kwargs else self.boxes),
            show_labels=(kwargs['show_labels'] if 'show_labels' in kwargs else self.show_labels),
            show_conf=(kwargs['show_conf'] if 'show_conf' in kwargs else self.show_conf)
        )
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break
        # cv2.waitKey(0)
        # print(results[0].boxes.data)
        if self.save or self.show:  # Add bbox blurred to image
            Anonymize.blur_results(self, **kwargs)
            self.vid_writer.release()

    def apply_track(self, **kwargs):
        # Get media width
        if self.mode == 'image':
            media = cv2.imread(self.input_media_path)
        else:
            media = cv2.VideoCapture(self.input_media_path)
            self.vid_writer = dict.fromkeys(range(int(media.get(cv2.CAP_PROP_FRAME_COUNT))))
        width = int(media.get(cv2.CAP_PROP_FRAME_WIDTH))
        if self.tracker is None:
            self.tracker = "botsort.yaml"
            # self.tracker = "bytetrack.yaml"

        # Apply model
        self.results = self.model.track(
            source=self.input_media_path,
            # stream=True,
            task='detect',
            tracker=self.tracker,
            device=self.device,
            imgsz=width,
            save=self.save,
            save_txt=self.save_txt,
            # classes2blur=(kwargs['classes2blur'] if 'classes2blur' in kwargs else self.classes2blur),
            # blur_ratio=(kwargs['blur_ratio'] if 'blur_ratio' in kwargs else self.blur_ratio),
            # ROI_enlargement=(kwargs['ROI_enlargement'] if 'ROI_enlargement' in kwargs else self.ROI_enlargement),
            conf=(kwargs['detection_threshold'] if 'detection_threshold' in kwargs else self.conf),
            show=(kwargs['show_preview'] if 'show_preview' in kwargs else self.show),
            boxes=(kwargs['show_boxes'] if 'show_boxes' in kwargs else self.boxes),
            show_labels=(kwargs['show_labels'] if 'show_labels' in kwargs else self.show_labels),
            show_conf=(kwargs['show_conf'] if 'show_conf' in kwargs else self.show_conf)
        )
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break
        # cv2.waitKey(0)
        # print(results[0].boxes.data)
        if self.save or self.show:  # Add bbox blurred to image
            Anonymize.blur_results(self, **kwargs)
            self.vid_writer.release()

    def blur_results(self, **kwargs):
        plot_args = {'line_width': self.line_width, 'boxes': False, 'conf': False, 'labels': False}
        classes2blur = (kwargs['classes2blur'] if 'classes2blur' in kwargs else self.classes2blur)
        blur_ratio = int((kwargs['blur_ratio'] if 'blur_ratio' in kwargs else self.blur_ratio)*100)
        ROI_enlargement = (kwargs['ROI_enlargement'] if 'ROI_enlargement' in kwargs else self.ROI_enlargement)
        conf = (kwargs['detection_threshold'] if 'detection_threshold' in kwargs else self.conf)
        Anonymize.setup_source(self)
        for idx, result in enumerate(self.results):
            im0 = result.plot(**plot_args)
            if len(classes2blur) and len(self.results[idx].boxes):
                for d in self.results[idx].boxes:
                    label = self.results[idx].names[int(d.cls)]
                    if label in classes2blur:
                        if label == 'face' or label == 'person':
                            crop_obj = im0[int(d.xyxy[0][1]):int(d.xyxy[0][3]), int(d.xyxy[0][0]):int(d.xyxy[0][2])]
                            blur = cv2.blur(crop_obj, (blur_ratio, blur_ratio))
                            im0[int(d.xyxy[0][1]):int(d.xyxy[0][3]), int(d.xyxy[0][0]):int(d.xyxy[0][2])] = blur
                        else:
                            crop_obj = im0[int(d.xyxy[0][1]):int(d.xyxy[0][3]), int(d.xyxy[0][0]):int(d.xyxy[0][2])]
                            blur = cv2.blur(crop_obj, (blur_ratio, blur_ratio))
                            im0[int(d.xyxy[0][1]):int(d.xyxy[0][3]), int(d.xyxy[0][0]):int(d.xyxy[0][2])] = blur
            self.plotted_img = im0
            Anonymize.save_preds(self)

    def save_preds(self):
        """Save video predictions as mp4 at specified path."""
        im0 = self.plotted_img
        if self.mode == 'image':  # 'image'
            cv2.imwrite(self.output_media_path, im0)
        else:  # 'video' or 'stream'
            self.vid_writer.write(im0)

    def setup_source(self):
        vid_cap = cv2.VideoCapture(self.input_media_path)
        fps = int(vid_cap.get(cv2.CAP_PROP_FPS))  # integer required, floats produce error in MP4 codec
        w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        suffix, fourcc = ('.mp4', 'avc1') if MACOS else ('.avi', 'WMV2') if WINDOWS else ('.avi', 'MJPG')
        save_path = str(Path(self.output_media_path).with_suffix(suffix))
        self.vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*fourcc), fps, (w, h))

# def copy_audio():
#     # copy over audio stream from original video to edited video
#     if is_installed("ffmpeg"):
#         ffmpeg_exe = "ffmpeg"
#     else:
#         ffmpeg_exe = os.getenv("FFMPEG_BINARY")
#         if not ffmpeg_exe:
#             print(
#                 "FFMPEG could not be found! Please make sure the ffmpeg.exe is available under the environment variable 'FFMPEG_BINARY'."
#             )
#             return
#
#     if audio_present:
#         subprocess.run(
#             [
#                 ffmpeg_exe,
#                 "-y",
#                 "-i",
#                 temp_output,
#                 "-i",
#                 input_path,
#                 "-c",
#                 "copy",
#                 "-map",
#                 "0:0",
#                 "-map",
#                 "1:1",
#                 "-shortest",
#                 output_path,
#             ],
#             stdout=subprocess.DEVNULL,

# def show_gpu_cache():
#     print("GPU Usage")
#     gpu_usage()

# def free_gpu_cache():
#     print("Initial GPU Usage")
#     gpu_usage()
#     torch.cuda.empty_cache()
#     cuda.select_device(0)
#     cuda.close()
#     cuda.select_device(0)
#     print("GPU Usage after emptying the cache")
#     gpu_usage()


if __name__ == '__main__':
    print('CUDA is currently available: ' + str(torch.cuda.is_available()))
    torch.cuda.empty_cache()
    gc.collect()
    # free_gpu_cache()
    model = Anonymize()
    if train:
        Anonymize.train_model(model)
    else:
        Anonymize.load_model(model)
    Anonymize.predict(model)
    # Anonymize.track(model)
