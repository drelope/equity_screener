import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score,recall_score,f1_score,average_precision_score,roc_auc_score,accuracy_score

FEATURES=["dividend_yield","dividend_growth","earnings_payout","fcf_payout",
"dividend_coverage","debt_to_ebitda","interest_coverage","volatility_252d",
"momentum_252d","momentum_63d","liquidation_discount","legal_rights_score",
"data_quality_score"]

def make_model():
    return Pipeline([
      ("imputer",SimpleImputer(strategy="median",add_indicator=True)),
      ("scale",StandardScaler()),
      ("model",LogisticRegression(max_iter=3000,class_weight="balanced",random_state=42))
    ])

def threshold_for_recall(y,p,min_recall=.30):
    best=.5; best_p=-1
    for t in np.linspace(.05,.95,181):
        pred=(p>=t).astype(int); r=recall_score(y,pred,zero_division=0)
        if r>=min_recall:
            q=precision_score(y,pred,zero_division=0)
            if q>best_p: best,best_p=t,q
    return best

def walk_forward(df,min_recall=.30):
    df=df.sort_values("as_of_date").dropna(subset=["target_sustainable_dividend"])
    dates=sorted(df.as_of_date.unique())
    cut=max(1,int(len(dates)*.70))
    train=df[df.as_of_date.isin(dates[:cut])]
    test=df[df.as_of_date.isin(dates[cut:])]
    m=make_model(); m.fit(train[FEATURES],train.target_sustainable_dividend.astype(int))
    threshold=threshold_for_recall(train.target_sustainable_dividend.astype(int),
                                   m.predict_proba(train[FEATURES])[:,1],min_recall)
    p=m.predict_proba(test[FEATURES])[:,1]
    pred=(p>=threshold).astype(int); y=test.target_sustainable_dividend.astype(int)
    metrics={
      "precision":precision_score(y,pred,zero_division=0),
      "recall":recall_score(y,pred,zero_division=0),
      "f1":f1_score(y,pred,zero_division=0),
      "pr_auc":average_precision_score(y,p),
      "roc_auc":roc_auc_score(y,p) if y.nunique()>1 else None,
      "accuracy":accuracy_score(y,pred),"threshold":threshold
    }
    return m,metrics,test.assign(probability=p,predicted_class=pred)
