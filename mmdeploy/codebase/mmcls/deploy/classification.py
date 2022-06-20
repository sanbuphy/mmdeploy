# Copyright (c) OpenMMLab. All rights reserved.
from copy import deepcopy
from typing import Dict, Optional, Sequence, Tuple, Union

import numpy as np
import torch
from mmengine import Config
from mmengine.model import BaseDataPreprocessor

from mmdeploy.codebase.base import BaseTask
from mmdeploy.utils import Task, get_root_logger
from mmdeploy.utils.config_utils import get_input_shape
from .mmclassification import MMCLS_TASK


def process_model_config(model_cfg: Config,
                         imgs: Union[str, np.ndarray],
                         input_shape: Optional[Sequence[int]] = None):
    """Process the model config.

    Args:
        model_cfg (Config): The model config.
        imgs (str | np.ndarray): Input image(s), accepted data type are `str`,
            `np.ndarray`.
        input_shape (list[int]): A list of two integer in (width, height)
            format specifying input shape. Default: None.

    Returns:
        Config: the model config after processing.
    """
    cfg = model_cfg.deepcopy()
    if isinstance(imgs, str):
        if cfg.test_pipeline[0]['type'] != 'LoadImageFromFile':
            cfg.test_pipeline.insert(0, dict(type='LoadImageFromFile'))
    else:
        if cfg.test_pipeline[0]['type'] == 'LoadImageFromFile':
            cfg.test_pipeline.pop(0)
    # check whether input_shape is valid
    if input_shape is not None:
        if 'crop_size' in cfg.test_pipeline[2]:
            crop_size = cfg.test_pipeline[2]['crop_size']
            if tuple(input_shape) != (crop_size, crop_size):
                logger = get_root_logger()
                logger.warning(
                    f'`input shape` should be equal to `crop_size`: {crop_size},\
                        but given: {input_shape}')
    return cfg


@MMCLS_TASK.register_module(Task.CLASSIFICATION.value)
class Classification(BaseTask):
    """Classification task class.

    Args:
        model_cfg (Config): Original PyTorch model config file.
        deploy_cfg (Config): Deployment config file or loaded Config
            object.
        device (str): A string represents device type.
    """

    def __init__(self,
                 model_cfg: Config,
                 deploy_cfg: Config,
                 device: str,
                 experiment_name: str = 'Classification'):
        super(Classification, self).__init__(model_cfg, deploy_cfg, device,
                                             experiment_name)

        if 'test_pipeline' in model_cfg:
            from mmcls.datasets.pipelines import Compose
            pipeline = model_cfg.test_pipeline
            if pipeline[0]['type'] != 'LoadImageFromFile':
                pipeline.insert(0, dict(type='LoadImageFromFile'))
            self.test_pipeline = Compose(pipeline)
        else:
            self.test_pipeline = None

    def init_backend_model(self,
                           model_files: Sequence[str] = None,
                           **kwargs) -> torch.nn.Module:
        """Initialize backend model.

        Args:
            model_files (Sequence[str]): Input model files.

        Returns:
            nn.Module: An initialized backend model.
        """
        from .classification_model import build_classification_model

        data_preprocessor = deepcopy(self.model_cfg.get('preprocess_cfg', {}))
        data_preprocessor.setdefault('type', 'mmcls.ClsDataPreprocessor')

        model = build_classification_model(
            model_files,
            self.model_cfg,
            self.deploy_cfg,
            device=self.device,
            data_preprocessor=data_preprocessor)
        model = model.to(self.device)
        return model.eval()

    def create_input(
        self,
        imgs: Union[str, np.ndarray],
        input_shape: Optional[Sequence[int]] = None,
        data_preprocessor: Optional[BaseDataPreprocessor] = None
    ) -> Tuple[Dict, torch.Tensor]:
        """Create input for classifier.

        Args:
            imgs (Any): Input image(s), accepted data type are `str`,
                `np.ndarray`, `torch.Tensor`.
            input_shape (list[int]): A list of two integer in (width, height)
                format specifying input shape. Default: None.

        Returns:
            tuple: (data, img), meta information for the input image and input.
        """
        if isinstance(imgs, str):
            data = {'img_path': imgs}
        else:
            data = {'img': imgs}
        data = self.test_pipeline(data)
        if data_preprocessor is not None:
            data = data_preprocessor([data], False)
            return data, data[0]
        else:
            return data, BaseTask.get_tensor_from_input(data)

    @staticmethod
    def get_partition_cfg(partition_type: str) -> Dict:
        """Get a certain partition config.

        Args:
            partition_type (str): A string specifying partition type.

        Returns:
            dict: A dictionary of partition config.
        """
        raise NotImplementedError('Not supported yet.')

    def get_preprocess(self) -> Dict:
        """Get the preprocess information for SDK.

        Return:
            dict: Composed of the preprocess information.
        """
        input_shape = get_input_shape(self.deploy_cfg)
        cfg = process_model_config(self.model_cfg, '', input_shape)
        preprocess = cfg.data.test.pipeline
        return preprocess

    def get_postprocess(self) -> Dict:
        """Get the postprocess information for SDK.

        Return:
            dict: Composed of the postprocess information.
        """
        postprocess = self.model_cfg.model.head
        assert 'topk' in postprocess, 'model config lack topk'
        postprocess.topk = max(postprocess.topk)
        return postprocess

    def get_model_name(self) -> str:
        """Get the model name.

        Return:
            str: the name of the model.
        """
        assert 'backbone' in self.model_cfg.model, 'backbone not in model '
        'config'
        assert 'type' in self.model_cfg.model.backbone, 'backbone contains '
        'no type'
        name = self.model_cfg.model.backbone.type.lower()
        return name
