"""
SOURCE: https://github.com/harupy/mlflow/tree/add-catboost-flavor

The ``cb_flavor`` module provides an API for logging and loading CatBoost models.
This module exports CatBoost models with the following flavors:
CatBoost (native) format
    This is the main flavor that can be loaded back into CatBoost.
:py:mod:`mlflow.pyfunc`
    Produced for use by generic pyfunc-based deployment tools and batch inference.
.. _CatBoost:
    https://catboost.ai/docs/concepts/python-reference_catboost.html
.. _CatBoost.save_model:
    https://catboost.ai/docs/concepts/python-reference_catboost_save_model.html
.. _CatBoostClassifier:
    https://catboost.ai/docs/concepts/python-reference_catboostclassifier.html
.. _CatBoostRegressor:
    https://catboost.ai/docs/concepts/python-reference_catboostregressor.html
"""

import os
import yaml

import cb_flavor

import mlflow
from mlflow import pyfunc
from mlflow.models import Model, ModelInputExample
from mlflow.models.model import MLMODEL_FILE_NAME
from mlflow.models.signature import ModelSignature
from mlflow.models.utils import _save_example
from mlflow.tracking.artifact_utils import _download_artifact_from_uri
from mlflow.utils.environment import _mlflow_conda_env
from mlflow.utils.model_utils import _get_flavor_configuration
from mlflow.exceptions import MlflowException

FLAVOR_NAME = "catboost"
_MODEL_TYPE_KEY_NAME = "model_type"


def get_default_conda_env():
    """
    :return: The default Conda environment for MLflow Models produced by calls to
             :func:`save_model()` and :func:`log_model()`.
    """
    import catboost as cb

    return _mlflow_conda_env(
        additional_conda_deps=None,
        # CatBoost is not yet available via the default conda channels, so we install it via pip
        additional_pip_deps=[
            "catboost=={}".format(cb.__version__),
        ],
        additional_conda_channels=None)


def save_model(cb_model, path, conda_env=None, mlflow_model=None,
               signature: ModelSignature = None, input_example: ModelInputExample = None,
               **kwargs):
    """
    Save a CatBoost model to a path on the local file system.
    :param cb_model: CatBoost model (an instance of `CatBoost`_, `CatBoostClassifier`_,
                     or `CatBoostRegressor`_) to be saved.
    :param path: Local path where the model is to be saved.
    :param conda_env: Either a dictionary representation of a Conda environment or the path to a
                      Conda environment yaml file. If provided, this describes the environment
                      this model should be run in. At minimum, it should specify the dependencies
                      contained in :func:`get_default_conda_env()`. If ``None``, the default
                      :func:`get_default_conda_env()` environment is added to the model.
                      The following is an *example* dictionary representation of a Conda
                      environment::
                        {
                            'name': 'mlflow-env',
                            'channels': ['defaults'],
                            'dependencies': [
                                'python=3.7.0',
                                'pip': [
                                    'catboost==0.19.1'
                                ]
                            ]
                        }
    :param mlflow_model: :py:mod:`mlflow.models.Model` this flavor is being added to.
    :param signature: (Experimental) :py:class:`ModelSignature <mlflow.models.ModelSignature>`
                      describes model input and output :py:class:`Schema <mlflow.types.Schema>`.
                      The model signature can be :py:func:`inferred <mlflow.models.infer_signature>`
                      from datasets with valid model input (e.g. the training dataset with target
                      column omitted) and valid model output (e.g. model predictions generated on
                      the training dataset), for example:
                      .. code-block:: python
                        from mlflow.models.signature import infer_signature
                        train = df.drop_column("target_label")
                        predictions = ... # compute model predictions
                        signature = infer_signature(train, predictions)
    :param input_example: (Experimental) Input example provides one or several instances of valid
                          model input. The example can be used as a hint of what data to feed the
                          model. The given example will be converted to a Pandas DataFrame and then
                          serialized to json using the Pandas split-oriented format. Bytes are
                          base64-encoded.
    :param kwargs: kwargs to pass to `CatBoost.save_model`_ method.
    """
    import catboost as cb

    path = os.path.abspath(path)
    if os.path.exists(path):
        raise MlflowException("Path '{}' already exists".format(path))
    os.makedirs(path)
    if mlflow_model is None:
        mlflow_model = Model()
    if signature is not None:
        mlflow_model.signature = signature
    if input_example is not None:
        _save_example(mlflow_model, input_example, path)
    model_data_subpath = "model.cb"
    model_data_path = os.path.join(path, model_data_subpath)

    # Save a CatBoost model
    cb_model.save_model(model_data_path, **kwargs)

    conda_env_subpath = "conda.yaml"
    if conda_env is None:
        conda_env = get_default_conda_env()
    elif not isinstance(conda_env, dict):
        with open(conda_env, "r") as f:
            conda_env = yaml.safe_load(f)
    with open(os.path.join(path, conda_env_subpath), "w") as f:
        yaml.safe_dump(conda_env, stream=f, default_flow_style=False)

    pyfunc.add_to_model(mlflow_model, loader_module="cb_flavor",
                        data=model_data_subpath, env=conda_env_subpath)
    mlflow_model.add_flavor(FLAVOR_NAME, cb_version=cb.__version__, data=model_data_subpath,
                            **{_MODEL_TYPE_KEY_NAME: cb_model.__class__.__name__})
    mlflow_model.save(os.path.join(path, MLMODEL_FILE_NAME))


def log_model(cb_model, artifact_path, conda_env=None, registered_model_name=None,
              signature: ModelSignature = None, input_example: ModelInputExample = None, **kwargs):
    """
    Log a CatBoost model as an MLflow artifact for the current run.
    :param cb_model: CatBoost model (an instance of `CatBoost`_, `CatBoostClassifier`_,
                     or `CatBoostRegressor`_) to be saved.
    :param artifact_path: Run-relative artifact path.
    :param conda_env: Either a dictionary representation of a Conda environment or the path to a
                      Conda environment yaml file. If provided, this describes the environment
                      this model should be run in. At minimum, it should specify the dependencies
                      contained in :func:`get_default_conda_env()`. If ``None``, the default
                      :func:`get_default_conda_env()` environment is added to the model.
                      The following is an *example* dictionary representation of a Conda
                      environment::
                        {
                            'name': 'mlflow-env',
                            'channels': ['defaults'],
                            'dependencies': [
                                'python=3.7.0',
                                'pip': [
                                    'catboost==0.19.1'
                                ]
                            ]
                        }
    :param registered_model_name: Note:: Experimental: This argument may change or be removed in a
                                  future release without warning. If given, create a model
                                  version under ``registered_model_name``, also creating a
                                  registered model if one with the given name does not exist.
    :param signature: (Experimental) :py:class:`ModelSignature <mlflow.models.ModelSignature>`
                      describes model input and output :py:class:`Schema <mlflow.types.Schema>`.
                      The model signature can be :py:func:`inferred <mlflow.models.infer_signature>`
                      from datasets with valid model input (e.g. the training dataset with target
                      column omitted) and valid model output (e.g. model predictions generated on
                      the training dataset), for example:
                      .. code-block:: python
                        from mlflow.models.signature import infer_signature
                        train = df.drop_column("target_label")
                        predictions = ... # compute model predictions
                        signature = infer_signature(train, predictions)
    :param input_example: (Experimental) Input example provides one or several instances of valid
                          model input. The example can be used as a hint of what data to feed the
                          model. The given example will be converted to a Pandas DataFrame and then
                          serialized to json using the Pandas split-oriented format. Bytes are
                          base64-encoded.
    :param kwargs: kwargs to pass to `CatBoost.save_model`_ method.
    """
    Model.log(artifact_path=artifact_path, flavor=cb_flavor,
              registered_model_name=registered_model_name,
              cb_model=cb_model, conda_env=conda_env,
              signature=signature, input_example=input_example, **kwargs)


def _create_model(model_type):
    import catboost as cb

    if model_type == cb.CatBoost.__name__:
        return cb.CatBoost()
    elif model_type == cb.CatBoostClassifier.__name__:
        return cb.CatBoostClassifier()
    elif model_type == cb.CatBoostRegressor.__name__:
        return cb.CatBoostRegressor()
    else:
        valid_types = [
            cb.CatBoost.__name__,
            cb.CatBoostClassifier.__name__,
            cb.CatBoostRegressor.__name__,
        ]
        raise TypeError(
            "Invalid model type. Expected one of {}, but got '{}'".format(valid_types, model_type)
        )


def _load_model(path, model_type):
    model = _create_model(model_type)
    model.load_model(os.path.abspath(path))
    return model


def _load_pyfunc(path):
    """
    Load PyFunc implementation. Called by ``pyfunc.load_pyfunc``.
    :param path: Local filesystem path to the MLflow Model with the ``catboost`` flavor.
    """
    flavor_conf = _get_flavor_configuration(
        model_path=os.path.dirname(path), flavor_name=FLAVOR_NAME
    )
    return _CatboostModelWrapper(
        _load_model(path, flavor_conf.get(_MODEL_TYPE_KEY_NAME))
    )


def load_model(model_uri):
    """
    Load a CatBoost model from a local file or a run.
    :param model_uri: The location, in URI format, of the MLflow model. For example:
                      - ``/Users/me/path/to/local/model``
                      - ``relative/path/to/local/model``
                      - ``s3://my_bucket/path/to/model``
                      - ``runs:/<mlflow_run_id>/run-relative/path/to/model``
                      For more information about supported URI schemes, see
                      `Referencing Artifacts <https://www.mlflow.org/docs/latest/tracking.html#
                      artifact-locations>`_.
    :return: A CatBoost model (an instance of `CatBoost`_, `CatBoostClassifier`_,
             or `CatBoostRegressor`_)
    """
    local_model_path = _download_artifact_from_uri(artifact_uri=model_uri)
    flavor_conf = _get_flavor_configuration(model_path=local_model_path, flavor_name=FLAVOR_NAME)
    cb_model_file_path = os.path.join(local_model_path, flavor_conf.get("data", "model.cb"))
    return _load_model(cb_model_file_path, flavor_conf.get(_MODEL_TYPE_KEY_NAME))


class _CatboostModelWrapper:
    def __init__(self, cb_model):
        self.cb_model = cb_model

    def predict(self, dataframe):
        return self.cb_model.predict(dataframe)