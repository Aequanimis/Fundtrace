# -*- coding: utf-8 -*-
"""
带约束的时间加权 Lasso 求解器（纯 numpy，无 scipy/sklearn 依赖）

问题形式：
    min_{β,c}  Σ_t w_t (y_t - x_t'β - c)²  +  α Σ_j β_j
    s.t.       β_j ≥ 0,  Σ_j β_j ≤ B

关键观察：在 β ≥ 0 的约束下，L1 惩罚 α·Σ|β_j| 退化为线性项 α·Σβ_j。
于是整个问题是一个凸二次规划，用 FISTA 加速投影梯度即可求解，
不需要 cvxpy / osqp 这类通用求解器。

截距 c 通过加权去心（weighted centering）消掉：
    ȳ = Σw·y / Σw,  x̄ = Σw·x / Σw
    在去心变量上求解 β，再令 c = ȳ - x̄'β
"""

import numpy as np


# ---------------------------------------------------------------- 投影

def project_capped_simplex(v, B):
    """把向量 v 投影到 {β ≥ 0, Σβ ≤ B}（欧氏投影）。

    两种情形：
      1) v 截断到非负后总和已 ≤ B  -> 直接返回截断结果
      2) 否则解在边界 Σβ = B 上    -> 用排序法投影到单纯形
    """
    B = float(B)
    if B <= 0:
        return np.zeros_like(v)

    w = np.maximum(v, 0.0)
    if w.sum() <= B + 1e-12:
        return w

    # 投影到 {β ≥ 0, Σβ = B}：求 θ 使 Σ max(v_j - θ, 0) = B
    u = np.sort(v)[::-1]
    css = np.cumsum(u) - B
    idx = np.arange(1, len(u) + 1)
    cond = u - css / idx > 0
    if not cond.any():
        # 数值兜底：均分
        return np.full_like(v, B / len(v))
    rho = idx[cond][-1]
    theta = css[rho - 1] / rho
    return np.maximum(v - theta, 0.0)


def project_box_simplex(v, B, cap=None, tol=1e-13, max_iter=100):
    """精确投影到 ``0 <= beta <= cap, sum(beta) <= B``。

    KKT 条件给出 ``beta_i = clip(v_i - theta, 0, cap_i)``。若和式约束
    激活，用单调二分求唯一的 ``theta``；K 很小（当前约 31），该实现简单
    且不引入生产依赖。
    """
    values = np.asarray(v, dtype=float)
    budget = max(float(B), 0.0)
    if cap is None:
        caps = np.full_like(values, np.inf)
    else:
        caps = np.maximum(np.asarray(cap, dtype=float), 0.0)
        if caps.shape != values.shape:
            raise ValueError("cap 与 beta 维度不一致")

    projected = np.minimum(np.maximum(values, 0.0), caps)
    if projected.sum() <= budget + tol:
        return projected
    if budget <= 0:
        return np.zeros_like(values)

    lower = float(np.min(values - np.where(np.isfinite(caps), caps, budget)))
    upper = float(np.max(values))
    for _ in range(max_iter):
        theta = (lower + upper) / 2.0
        projected = np.minimum(np.maximum(values - theta, 0.0), caps)
        total = float(projected.sum())
        if abs(total - budget) <= tol:
            break
        if total > budget:
            lower = theta
        else:
            upper = theta
    projected = np.minimum(np.maximum(values - upper, 0.0), caps)
    return projected


# ---------------------------------------------------------------- 求解

def solve_weighted_lasso_legacy(
    X, y, w=None, alpha=0.0, max_sum=1.0,
    max_iter=2000, tol=1e-9, verbose=False,
):
    """求解带约束的时间加权 Lasso。

    参数
    ----
    X : (T, K) 自变量（各行业子组合日收益）
    y : (T,)   因变量（基金日收益）
    w : (T,)   时间权重，None 表示等权
    alpha : L1 惩罚强度（β≥0 下等价于线性惩罚）
    max_sum : Σβ 的上界（该基金的权益仓位上限）
    tol : 相邻两次迭代 β 的最大变动小于该值即收敛

    返回
    ----
    dict: beta / intercept / r2 / n_iter / converged / resid_std
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).ravel()
    T, K = X.shape

    if w is None:
        w = np.ones(T)
    w = np.asarray(w, dtype=float).ravel()
    w = w / w.sum()

    # --- 加权去心，消掉截距
    xbar = (w[:, None] * X).sum(axis=0)
    ybar = float((w * y).sum())
    Xc = X - xbar
    yc = y - ybar

    # --- 预计算（加权正规方程的两块）
    WX = w[:, None] * Xc
    A = Xc.T @ WX          # (K,K)  = X'WX
    b = WX.T @ yc          # (K,)   = X'Wy

    # Lipschitz 常数：梯度 = 2(Aβ - b) + α，L = 2·λmax(A)
    try:
        lmax = float(np.linalg.eigvalsh(A).max())
    except np.linalg.LinAlgError:
        lmax = float(np.trace(A))
    L = 2.0 * max(lmax, 1e-12)
    step = 1.0 / L

    # --- FISTA
    beta = np.zeros(K)
    z = beta.copy()
    t_k = 1.0
    converged = False
    it = 0

    for it in range(1, max_iter + 1):
        grad = 2.0 * (A @ z - b) + alpha
        beta_new = project_capped_simplex(z - step * grad, max_sum)

        delta = np.max(np.abs(beta_new - beta))
        t_next = (1.0 + np.sqrt(1.0 + 4.0 * t_k * t_k)) / 2.0
        z = beta_new + ((t_k - 1.0) / t_next) * (beta_new - beta)

        beta, t_k = beta_new, t_next

        if delta < tol:
            converged = True
            break

    beta = np.where(beta < 1e-10, 0.0, beta)   # 清理数值噪声
    intercept = ybar - xbar @ beta

    # --- 拟合优度（加权 R²）
    pred = X @ beta + intercept
    resid = y - pred
    ss_res = float((w * resid ** 2).sum())
    ss_tot = float((w * (y - ybar) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-18 else np.nan

    if verbose:
        print(f"  iter={it}  converged={converged}  R²={r2:.4f}  Σβ={beta.sum():.4f}")

    return {
        "beta": beta,
        "intercept": float(intercept),
        "r2": float(r2) if np.isfinite(r2) else np.nan,
        "n_iter": it,
        "converged": converged,
        "resid_std": float(np.sqrt(ss_res)),
        "sum_beta": float(beta.sum()),
    }


def solve_weighted_lasso(
    X, y, w=None, alpha=0.0, max_sum=1.0, cap_vec=None,
    max_iter=2000, tol=1e-10, verbose=False,
):
    """生产 FISTA：adaptive restart + projected KKT + 精确 box-simplex。"""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).ravel()
    T, K = X.shape
    if w is None:
        w = np.ones(T)
    w = np.asarray(w, dtype=float).ravel()
    w = w / w.sum()

    xbar = (w[:, None] * X).sum(axis=0)
    ybar = float((w * y).sum())
    Xc = X - xbar
    yc = y - ybar
    WX = w[:, None] * Xc
    A = Xc.T @ WX
    b = WX.T @ yc
    try:
        lmax = float(np.linalg.eigvalsh(A).max())
    except np.linalg.LinAlgError:
        lmax = float(np.trace(A))
    lipschitz = 2.0 * max(lmax, 1e-12)
    step = 1.0 / lipschitz

    caps = None if cap_vec is None else np.maximum(np.asarray(cap_vec, dtype=float), 0.0)
    beta = project_box_simplex(np.zeros(K), max_sum, caps)
    z = beta.copy()
    momentum = 1.0
    converged = False
    kkt_residual = np.inf

    for iteration in range(1, max_iter + 1):
        grad_z = 2.0 * (A @ z - b) + alpha
        beta_new = project_box_simplex(z - step * grad_z, max_sum, caps)

        grad_beta = 2.0 * (A @ beta_new - b) + alpha
        kkt_point = project_box_simplex(beta_new - step * grad_beta, max_sum, caps)
        kkt_residual = float(np.max(np.abs(beta_new - kkt_point)))
        if kkt_residual <= tol:
            beta = beta_new
            converged = True
            break

        next_momentum = (1.0 + np.sqrt(1.0 + 4.0 * momentum * momentum)) / 2.0
        candidate_z = beta_new + ((momentum - 1.0) / next_momentum) * (beta_new - beta)
        # Gradient-scheme adaptive restart; avoids oscillation near active bounds.
        if float(np.dot(z - beta_new, beta_new - beta)) > 0.0:
            momentum = 1.0
            z = beta_new.copy()
        else:
            momentum = next_momentum
            z = candidate_z
        beta = beta_new
    else:
        iteration = max_iter

    beta = project_box_simplex(np.where(beta < 1e-12, 0.0, beta), max_sum, caps)
    intercept = ybar - xbar @ beta
    pred = X @ beta + intercept
    resid = y - pred
    ss_res = float((w * resid ** 2).sum())
    ss_tot = float((w * (y - ybar) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-18 else np.nan

    if verbose:
        print(
            f"  iter={iteration} converged={converged} KKT={kkt_residual:.2e} "
            f"R²={r2:.4f} Σβ={beta.sum():.4f}"
        )
    return {
        "beta": beta,
        "intercept": float(intercept),
        "r2": float(r2) if np.isfinite(r2) else np.nan,
        "n_iter": iteration,
        "converged": converged,
        "kkt_residual": kkt_residual,
        "resid_std": float(np.sqrt(ss_res)),
        "sum_beta": float(beta.sum()),
    }


# ---------------------------------------------------------------- 时间权重

def exp_decay_weights(n, half_life):
    """指数衰减时间权重，最新一期权重最大。

    half_life 为半衰期（交易日）。half_life <= 0 表示等权。
    """
    if half_life is None or half_life <= 0:
        return np.ones(n)
    age = np.arange(n - 1, -1, -1, dtype=float)   # 最后一行 age=0
    return 0.5 ** (age / float(half_life))


# ---------------------------------------------------------------- 自测

def _self_test():
    """用已知真实系数的合成数据验证求解器。"""
    rng = np.random.default_rng(42)
    T, K = 250, 31

    # 真实仓位：稀疏、非负、总和 0.88
    true_beta = np.zeros(K)
    active = rng.choice(K, size=7, replace=False)
    true_beta[active] = rng.uniform(0.03, 0.25, size=7)
    true_beta = true_beta / true_beta.sum() * 0.88

    X = rng.normal(0, 0.015, size=(T, K))
    noise = rng.normal(0, 0.0012, size=T)
    y = X @ true_beta + 0.0001 + noise

    print("=" * 64)
    print("求解器自测")
    print("=" * 64)

    # --- 1. 无惩罚，应几乎精确还原
    r = solve_weighted_lasso(X, y, alpha=0.0, max_sum=1.0)
    err = np.abs(r["beta"] - true_beta).mean()
    print(f"[1] 无惩罚      MAE={err:.5f}  R²={r['r2']:.4f}  "
          f"Σβ={r['sum_beta']:.4f}(真值0.8800)  收敛={r['converged']}")
    assert err < 0.01, f"无惩罚情形误差过大: {err}"

    # --- 2. 加 L1，应更稀疏且仍接近
    r2_ = solve_weighted_lasso(X, y, alpha=1e-6, max_sum=1.0)
    nz = (r2_["beta"] > 1e-6).sum()
    err2 = np.abs(r2_["beta"] - true_beta).mean()
    print(f"[2] 加L1惩罚    MAE={err2:.5f}  非零={nz}个(真实7个)  R²={r2_['r2']:.4f}")

    # --- 3. 非负约束必须严格成立
    assert (r["beta"] >= -1e-12).all(), "出现负仓位"
    print(f"[3] 非负约束    min(β)={r['beta'].min():.2e}  OK")

    # --- 4. 和式约束必须严格成立
    r3 = solve_weighted_lasso(X, y, alpha=0.0, max_sum=0.60)
    print(f"[4] 和式约束    Σβ={r3['sum_beta']:.6f} ≤ 0.60  "
          f"{'OK' if r3['sum_beta'] <= 0.6 + 1e-6 else 'FAIL'}")
    assert r3["sum_beta"] <= 0.6 + 1e-6, "违反和式约束"

    # --- 5. 时间权重：让后半段换一组真实仓位，加权后应更贴近后半段
    beta_late = np.zeros(K)
    active2 = rng.choice(K, size=7, replace=False)
    beta_late[active2] = rng.uniform(0.03, 0.25, size=7)
    beta_late = beta_late / beta_late.sum() * 0.88
    y2 = y.copy()
    y2[T // 2:] = X[T // 2:] @ beta_late + 0.0001 + noise[T // 2:]

    r_eq = solve_weighted_lasso(X, y2, alpha=0.0, max_sum=1.0)
    r_w = solve_weighted_lasso(X, y2, w=exp_decay_weights(T, 40), alpha=0.0, max_sum=1.0)
    d_eq = np.abs(r_eq["beta"] - beta_late).mean()
    d_w = np.abs(r_w["beta"] - beta_late).mean()
    print(f"[5] 时间权重    等权距新仓位 MAE={d_eq:.5f}  "
          f"加权距新仓位 MAE={d_w:.5f}  {'OK(加权更近)' if d_w < d_eq else 'FAIL'}")
    assert d_w < d_eq, "时间加权未起作用"

    # --- 6. 投影函数边界情形
    assert np.allclose(project_capped_simplex(np.array([-1.0, -2.0]), 1.0), [0, 0])
    p = project_capped_simplex(np.array([0.9, 0.9]), 1.0)
    assert abs(p.sum() - 1.0) < 1e-9 and (p >= 0).all()
    print(f"[6] 投影边界    OK")

    print("=" * 64)
    print("全部通过")
    print("=" * 64)


if __name__ == "__main__":
    _self_test()
