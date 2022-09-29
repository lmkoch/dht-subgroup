import os

import numpy as np
import pandas as pd
from utils.helpers import stderr_proportion

from core.dataset import dataset_fn
from core.model import DomainClassifier, MaxKernel, TaskClassifier


def eval(
    trainer,
    model,
    ckpt_path,
    params,
    split="test",  # FIXME need additional logic with trainer.validate
    sample_sizes=[10, 30, 50, 100, 500],
):
    """Analysis of test power vs sample size for both MMD-D and MUKS

    Args:
        exp_dir ([type]): exp base directory
        exp_name ([type]): experiment name (hashed config)
        params (Dict): [description]
        split (str): fold to evaluate, e.g. 'validation' or 'test
        sample_sizes (list, optional): Defaults to [10, 30, 50, 100, 500].
        num_reps (int, optional): for calculation rejection rates. Defaults to 100.
        num_permutations (int, optional): for MMD-D permutation test. Defaults to 1000.
    """

    log_dir = trainer.logger.log_dir
    out_csv = os.path.join(log_dir, f"{split}_consistency_analysis.csv")

    df = pd.DataFrame(columns=["sample_size", "power", "type_1err", "method"])

    from core.model import DataModule

    if isinstance(model, TaskClassifier):
        test_type = "muks"
        boot_strap_test = False

        model.test_sample_sizes = sample_sizes

        dataloader = dataset_fn(params_dict=params["dataset"])
        trainer.test(model=model, ckpt_path=ckpt_path, datamodule=DataModule(dataloader))
        return

    elif isinstance(model, MaxKernel):
        test_type = "mmdd"
        boot_strap_test = True
    elif isinstance(model, DomainClassifier):
        test_type = "c2st"
        boot_strap_test = False
    else:
        raise ValueError(f"Unsupported model: {trainer.model}")

    for batch_size in sample_sizes:

        params["dataset"]["dl"]["batch_size"] = batch_size

        dataloader = dataset_fn(params_dict=params["dataset"], boot_strap_test=boot_strap_test)

        res = trainer.test(model=model, ckpt_path=ckpt_path, datamodule=DataModule(dataloader))[0]
        reject_rate = res["test/power"]

        if test_type == "mmdd":
            # MMD-D lightning model cannot natively calculate type 1 error - need to
            # calculate power on same distribution
            import copy

            type_1_err_params = copy.deepcopy(params)
            type_1_err_params["dataset"]["ds"]["q"] = type_1_err_params["dataset"]["ds"]["p"]

            dataloader = dataset_fn(
                params_dict=type_1_err_params["dataset"], boot_strap_test=boot_strap_test
            )
            res = trainer.test(
                model=model, ckpt_path=ckpt_path, datamodule=DataModule(dataloader)
            )[0]

            type_1_err = res["test/power"]

        else:
            type_1_err = res["test/type_1err"]

        res = {
            "sample_size": batch_size,
            "power": reject_rate,
            "type_1err": type_1_err,
        }

        df = df.append(pd.DataFrame(res, index=[""]), ignore_index=True)

        print(res)

    df["power_stderr"] = stderr_proportion(df["power"], df["sample_size"].astype(float))
    df["type_1err_stderr"] = stderr_proportion(df["type_1err"], df["sample_size"].astype(float))

    df.to_csv(out_csv)
