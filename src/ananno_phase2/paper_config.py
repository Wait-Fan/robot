"""论文明确参数与可追踪的实现假设；默认值不是作者实验配置的声明。"""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class PaperConfig:
    full_layer_fill: float = .90
    half_layer_fill: float = .90
    quarter_layer_fill: float = .85
    corner_inset_fraction: float = .01
    com_deviation_fraction: float = .25
    pallet_weight: float = 25.0
    pallet_com_height: float = 0.0
    missing_weight: float = 1.0
    acceleration_x: float = 0.0
    acceleration_y: float = 0.0
    gravity: float = 9.81
    population_size: int = 100
    mu: int = 15
    lambda_: int = 30
    crossover_probability: float = .5
    mutation_probability: float = .2
    generations: int = 30
    max_stagnation: int = 5
    seed: int = 42
    max_pallets: int = 100

    def __post_init__(self):
        for name,value in asdict(self).items():
            if not isinstance(value,(float,int)) or not math.isfinite(value):
                raise ValueError(f"{name} 必须是有限数值")
        for name in ("full_layer_fill","half_layer_fill","quarter_layer_fill","crossover_probability","mutation_probability"):
            if not 0<=getattr(self,name)<=1: raise ValueError(f"{name} 必须位于[0,1]")
        if self.crossover_probability+self.mutation_probability>1: raise ValueError("交叉和变异概率之和不能超过1")
        if not 0<=self.corner_inset_fraction<.5: raise ValueError("角点内缩比例必须位于[0,0.5)")
        if not 0<self.com_deviation_fraction<=.5: raise ValueError("COM偏移比例必须位于(0,0.5]")
        for name in ("population_size","mu","lambda_","generations","max_stagnation","max_pallets"):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int) or value<1: raise ValueError(f"{name} 必须为正整数")
        if self.mu>self.population_size: raise ValueError("mu不能超过初始种群数量")
        if isinstance(self.seed,bool) or not isinstance(self.seed,int): raise ValueError("随机种子必须为整数")
        if self.pallet_weight<0 or self.missing_weight<=0 or self.gravity<=0: raise ValueError("托盘质量不得为负，替代重量和重力必须为正")
        if self.acceleration_x<0 or self.acceleration_y<0: raise ValueError("加速度幅值不能为负")

    def to_dict(self): return asdict(self)
