# coding=utf-8
# Copyright 2021 HuggingFace Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import json
import pathlib
import unittest

from transformers.testing_utils import require_torch, require_vision, slow
from transformers.utils import is_torch_available, is_vision_available

from ...test_image_processing_common import AnnotationFormatTestMixin, ImageProcessingTestMixin, prepare_image_inputs


if is_torch_available():
    import torch

if is_vision_available():
    from PIL import Image

    from transformers import DetrImageProcessor


class DetrImageProcessingTester(unittest.TestCase):
    def __init__(
        self,
        parent,
        batch_size=7,
        num_channels=3,
        min_resolution=30,
        max_resolution=400,
        do_resize=True,
        size=None,
        do_rescale=True,
        rescale_factor=1 / 255,
        do_normalize=True,
        image_mean=[0.5, 0.5, 0.5],
        image_std=[0.5, 0.5, 0.5],
        do_pad=True,
    ):
        # by setting size["longest_edge"] > max_resolution we're effectively not testing this :p
        size = size if size is not None else {"shortest_edge": 18, "longest_edge": 1333}
        self.parent = parent
        self.batch_size = batch_size
        self.num_channels = num_channels
        self.min_resolution = min_resolution
        self.max_resolution = max_resolution
        self.do_resize = do_resize
        self.size = size
        self.do_rescale = do_rescale
        self.rescale_factor = rescale_factor
        self.do_normalize = do_normalize
        self.image_mean = image_mean
        self.image_std = image_std
        self.do_pad = do_pad

    def prepare_image_processor_dict(self):
        return {
            "do_resize": self.do_resize,
            "size": self.size,
            "do_rescale": self.do_rescale,
            "rescale_factor": self.rescale_factor,
            "do_normalize": self.do_normalize,
            "image_mean": self.image_mean,
            "image_std": self.image_std,
            "do_pad": self.do_pad,
        }

    def get_expected_values(self, image_inputs, batched=False):
        """
        This function computes the expected height and width when providing images to DetrImageProcessor,
        assuming do_resize is set to True with a scalar size.
        """
        if not batched:
            image = image_inputs[0]
            if isinstance(image, Image.Image):
                w, h = image.size
            else:
                h, w = image.shape[1], image.shape[2]
            if w < h:
                expected_height = int(self.size["shortest_edge"] * h / w)
                expected_width = self.size["shortest_edge"]
            elif w > h:
                expected_height = self.size["shortest_edge"]
                expected_width = int(self.size["shortest_edge"] * w / h)
            else:
                expected_height = self.size["shortest_edge"]
                expected_width = self.size["shortest_edge"]

        else:
            expected_values = []
            for image in image_inputs:
                expected_height, expected_width = self.get_expected_values([image])
                expected_values.append((expected_height, expected_width))
            expected_height = max(expected_values, key=lambda item: item[0])[0]
            expected_width = max(expected_values, key=lambda item: item[1])[1]

        return expected_height, expected_width

    def expected_output_image_shape(self, images):
        height, width = self.get_expected_values(images, batched=True)
        return self.num_channels, height, width

    def prepare_image_inputs(self, equal_resolution=False, numpify=False, torchify=False):
        return prepare_image_inputs(
            batch_size=self.batch_size,
            num_channels=self.num_channels,
            min_resolution=self.min_resolution,
            max_resolution=self.max_resolution,
            equal_resolution=equal_resolution,
            numpify=numpify,
            torchify=torchify,
        )


@require_torch
@require_vision
class DetrImageProcessingTest(AnnotationFormatTestMixin, ImageProcessingTestMixin, unittest.TestCase):
    image_processing_class = DetrImageProcessor if is_vision_available() else None

    def setUp(self):
        self.image_processor_tester = DetrImageProcessingTester(self)

    @property
    def image_processor_dict(self):
        return self.image_processor_tester.prepare_image_processor_dict()

    def test_image_processor_properties(self):
        image_processing = self.image_processing_class(**self.image_processor_dict)
        self.assertTrue(hasattr(image_processing, "image_mean"))
        self.assertTrue(hasattr(image_processing, "image_std"))
        self.assertTrue(hasattr(image_processing, "do_normalize"))
        self.assertTrue(hasattr(image_processing, "do_rescale"))
        self.assertTrue(hasattr(image_processing, "rescale_factor"))
        self.assertTrue(hasattr(image_processing, "do_resize"))
        self.assertTrue(hasattr(image_processing, "size"))
        self.assertTrue(hasattr(image_processing, "do_pad"))

    def test_image_processor_from_dict_with_kwargs(self):
        image_processor = self.image_processing_class.from_dict(self.image_processor_dict)
        self.assertEqual(image_processor.size, {"shortest_edge": 18, "longest_edge": 1333})
        self.assertEqual(image_processor.do_pad, True)

        image_processor = self.image_processing_class.from_dict(
            self.image_processor_dict, size=42, max_size=84, pad_and_return_pixel_mask=False
        )
        self.assertEqual(image_processor.size, {"shortest_edge": 42, "longest_edge": 84})
        self.assertEqual(image_processor.do_pad, False)

    def test_should_raise_if_annotation_format_invalid(self):
        image_processor_dict = self.image_processor_tester.prepare_image_processor_dict()

        with open("./tests/fixtures/tests_samples/COCO/coco_annotations.txt", "r") as f:
            detection_target = json.loads(f.read())

        annotations = {"image_id": 39769, "annotations": detection_target}

        params = {
            "images": Image.open("./tests/fixtures/tests_samples/COCO/000000039769.png"),
            "annotations": annotations,
            "return_tensors": "pt",
        }

        image_processor_params = {**image_processor_dict, **{"format": "_INVALID_FORMAT_"}}
        image_processor = self.image_processing_class(**image_processor_params)

        with self.assertRaises(ValueError) as e:
            image_processor(**params)

        self.assertTrue(str(e.exception).startswith("_INVALID_FORMAT_ is not a valid AnnotationFormat"))

    def test_valid_coco_detection_annotations(self):
        # prepare image and target
        image = Image.open("./tests/fixtures/tests_samples/COCO/000000039769.png")
        with open("./tests/fixtures/tests_samples/COCO/coco_annotations.txt", "r") as f:
            target = json.loads(f.read())

        params = {"image_id": 39769, "annotations": target}

        # encode them
        image_processing = DetrImageProcessor.from_pretrained("facebook/detr-resnet-50")

        # legal encodings (single image)
        _ = image_processing(images=image, annotations=params, return_tensors="pt")
        _ = image_processing(images=image, annotations=[params], return_tensors="pt")

        # legal encodings (batch of one image)
        _ = image_processing(images=[image], annotations=params, return_tensors="pt")
        _ = image_processing(images=[image], annotations=[params], return_tensors="pt")

        # legal encoding (batch of more than one image)
        n = 5
        _ = image_processing(images=[image] * n, annotations=[params] * n, return_tensors="pt")

        # example of an illegal encoding (missing the 'image_id' key)
        with self.assertRaises(ValueError) as e:
            image_processing(images=image, annotations={"annotations": target}, return_tensors="pt")

        self.assertTrue(str(e.exception).startswith("Invalid COCO detection annotations"))

        # example of an illegal encoding (unequal lengths of images and annotations)
        with self.assertRaises(ValueError) as e:
            image_processing(images=[image] * n, annotations=[params] * (n - 1), return_tensors="pt")

        self.assertTrue(str(e.exception) == "The number of images (5) and annotations (4) do not match.")

    @slow
    def test_call_pytorch_with_coco_detection_annotations(self):
        # prepare image and target
        image = Image.open("./tests/fixtures/tests_samples/COCO/000000039769.png")
        with open("./tests/fixtures/tests_samples/COCO/coco_annotations.txt", "r") as f:
            target = json.loads(f.read())

        target = {"image_id": 39769, "annotations": target}

        # encode them
        image_processing = DetrImageProcessor.from_pretrained("facebook/detr-resnet-50")
        encoding = image_processing(images=image, annotations=target, return_tensors="pt")

        # verify pixel values
        expected_shape = torch.Size([1, 3, 800, 1066])
        self.assertEqual(encoding["pixel_values"].shape, expected_shape)

        expected_slice = torch.tensor([0.2796, 0.3138, 0.3481])
        self.assertTrue(torch.allclose(encoding["pixel_values"][0, 0, 0, :3], expected_slice, atol=1e-4))

        # verify area
        expected_area = torch.tensor([5887.9600, 11250.2061, 489353.8438, 837122.7500, 147967.5156, 165732.3438])
        self.assertTrue(torch.allclose(encoding["labels"][0]["area"], expected_area))
        # verify boxes
        expected_boxes_shape = torch.Size([6, 4])
        self.assertEqual(encoding["labels"][0]["boxes"].shape, expected_boxes_shape)
        expected_boxes_slice = torch.tensor([0.5503, 0.2765, 0.0604, 0.2215])
        self.assertTrue(torch.allclose(encoding["labels"][0]["boxes"][0], expected_boxes_slice, atol=1e-3))
        # verify image_id
        expected_image_id = torch.tensor([39769])
        self.assertTrue(torch.allclose(encoding["labels"][0]["image_id"], expected_image_id))
        # verify is_crowd
        expected_is_crowd = torch.tensor([0, 0, 0, 0, 0, 0])
        self.assertTrue(torch.allclose(encoding["labels"][0]["iscrowd"], expected_is_crowd))
        # verify class_labels
        expected_class_labels = torch.tensor([75, 75, 63, 65, 17, 17])
        self.assertTrue(torch.allclose(encoding["labels"][0]["class_labels"], expected_class_labels))
        # verify orig_size
        expected_orig_size = torch.tensor([480, 640])
        self.assertTrue(torch.allclose(encoding["labels"][0]["orig_size"], expected_orig_size))
        # verify size
        expected_size = torch.tensor([800, 1066])
        self.assertTrue(torch.allclose(encoding["labels"][0]["size"], expected_size))

    @slow
    def test_call_pytorch_with_coco_panoptic_annotations(self):
        # prepare image, target and masks_path
        image = Image.open("./tests/fixtures/tests_samples/COCO/000000039769.png")
        with open("./tests/fixtures/tests_samples/COCO/coco_panoptic_annotations.txt", "r") as f:
            target = json.loads(f.read())

        target = {"file_name": "000000039769.png", "image_id": 39769, "segments_info": target}

        masks_path = pathlib.Path("./tests/fixtures/tests_samples/COCO/coco_panoptic")

        # encode them
        image_processing = DetrImageProcessor.from_pretrained("facebook/detr-resnet-50-panoptic")
        encoding = image_processing(images=image, annotations=target, masks_path=masks_path, return_tensors="pt")

        # verify pixel values
        expected_shape = torch.Size([1, 3, 800, 1066])
        self.assertEqual(encoding["pixel_values"].shape, expected_shape)

        expected_slice = torch.tensor([0.2796, 0.3138, 0.3481])
        self.assertTrue(torch.allclose(encoding["pixel_values"][0, 0, 0, :3], expected_slice, atol=1e-4))

        # verify area
        expected_area = torch.tensor([147979.6875, 165527.0469, 484638.5938, 11292.9375, 5879.6562, 7634.1147])
        self.assertTrue(torch.allclose(encoding["labels"][0]["area"], expected_area))
        # verify boxes
        expected_boxes_shape = torch.Size([6, 4])
        self.assertEqual(encoding["labels"][0]["boxes"].shape, expected_boxes_shape)
        expected_boxes_slice = torch.tensor([0.2625, 0.5437, 0.4688, 0.8625])
        self.assertTrue(torch.allclose(encoding["labels"][0]["boxes"][0], expected_boxes_slice, atol=1e-3))
        # verify image_id
        expected_image_id = torch.tensor([39769])
        self.assertTrue(torch.allclose(encoding["labels"][0]["image_id"], expected_image_id))
        # verify is_crowd
        expected_is_crowd = torch.tensor([0, 0, 0, 0, 0, 0])
        self.assertTrue(torch.allclose(encoding["labels"][0]["iscrowd"], expected_is_crowd))
        # verify class_labels
        expected_class_labels = torch.tensor([17, 17, 63, 75, 75, 93])
        self.assertTrue(torch.allclose(encoding["labels"][0]["class_labels"], expected_class_labels))
        # verify masks
        expected_masks_sum = 822873
        self.assertEqual(encoding["labels"][0]["masks"].sum().item(), expected_masks_sum)
        # verify orig_size
        expected_orig_size = torch.tensor([480, 640])
        self.assertTrue(torch.allclose(encoding["labels"][0]["orig_size"], expected_orig_size))
        # verify size
        expected_size = torch.tensor([800, 1066])
        self.assertTrue(torch.allclose(encoding["labels"][0]["size"], expected_size))
