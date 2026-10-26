from lightgbm import LGBMClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


RANDOM_STATE = 42


def make_logistic_model():
    return make_pipeline(
        SimpleImputer(
            strategy="median",
            add_indicator=True,
        ),
        StandardScaler(),
        LogisticRegression(
            max_iter=2000,
            random_state=RANDOM_STATE,
        ),
    )


def make_lightgbm_model():
    return LGBMClassifier(
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=15,
        min_child_samples=100,
        colsample_bytree=0.8,
        reg_lambda=5.0,
        random_state=RANDOM_STATE,
        n_jobs=4,
        verbosity=-1,
    )


def make_xgboost_model():
    return XGBClassifier(
        n_estimators=300,
        learning_rate=0.03,
        max_depth=3,
        min_child_weight=10,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=5.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=4,
    )


def make_hist_gradient_boosting_model():
    return HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.03,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        l2_regularization=5.0,
        early_stopping=False,
        random_state=RANDOM_STATE,
    )