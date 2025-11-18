#!/usr/bin/env python3
"""
AWS Cost Calculator for Quant AI Project
Calculates estimated costs based on usage patterns
"""

from datetime import datetime
from typing import Dict

# AWS Pricing (us-east-1, as of Nov 2024)
PRICING = {
    "ec2": {
        "t3.micro": 0.0104,      # per hour - FREE TIER: 750 hours/month
        "t3.medium": 0.0416,      # per hour
        "g4dn.xlarge": 0.526,     # per hour (GPU)
    },
    "ebs": {
        "gp3": 0.08,              # per GB/month
    },
    "s3": {
        "standard": 0.023,        # per GB/month
    },
    "data_transfer": {
        "out": 0.09,              # per GB (first 10TB)
    },
    "rds": {
        "db.t3.small": 0.034,     # per hour
    }
}

FREE_TIER = {
    "ec2_hours": 750,             # t2.micro/t3.micro hours per month
    "ebs_gb": 30,                 # GB general purpose SSD
    "s3_gb": 5,                   # GB standard storage
    "data_transfer_gb": 100,      # GB outbound per month
}


class CostCalculator:
    """Calculate AWS costs for different deployment scenarios."""
    
    def __init__(self, use_free_tier: bool = True):
        self.use_free_tier = use_free_tier
    
    def calculate_ec2_cost(self, instance_type: str, hours: float, count: int = 1) -> float:
        """Calculate EC2 instance cost."""
        hourly_rate = PRICING["ec2"][instance_type]
        total_hours = hours * count
        
        if self.use_free_tier and instance_type == "t3.micro":
            free_hours = min(total_hours, FREE_TIER["ec2_hours"])
            billable_hours = max(0, total_hours - free_hours)
            cost = billable_hours * hourly_rate
        else:
            cost = total_hours * hourly_rate
        
        return cost
    
    def calculate_ebs_cost(self, gb: int, months: float = 1) -> float:
        """Calculate EBS storage cost."""
        if self.use_free_tier:
            billable_gb = max(0, gb - FREE_TIER["ebs_gb"])
        else:
            billable_gb = gb
        
        return billable_gb * PRICING["ebs"]["gp3"] * months
    
    def calculate_s3_cost(self, gb: int, months: float = 1) -> float:
        """Calculate S3 storage cost."""
        if self.use_free_tier:
            billable_gb = max(0, gb - FREE_TIER["s3_gb"])
        else:
            billable_gb = gb
        
        return billable_gb * PRICING["s3"]["standard"] * months
    
    def calculate_data_transfer_cost(self, gb: int) -> float:
        """Calculate data transfer cost."""
        if self.use_free_tier:
            billable_gb = max(0, gb - FREE_TIER["data_transfer_gb"])
        else:
            billable_gb = gb
        
        return billable_gb * PRICING["data_transfer"]["out"]
    
    def scenario_basic_test(self, hours: float = 24) -> Dict[str, float]:
        """Basic test deployment cost (t3.micro only)."""
        costs = {
            "ec2_test": self.calculate_ec2_cost("t3.micro", hours),
            "ebs_test": self.calculate_ebs_cost(8, hours / 730),
            "s3": self.calculate_s3_cost(1, hours / 730),
            "data_transfer": self.calculate_data_transfer_cost(1),
        }
        costs["total"] = sum(costs.values())
        return costs
    
    def scenario_with_gpu(self, hours: float = 24) -> Dict[str, float]:
        """Test with GPU model server."""
        costs = {
            "ec2_test": self.calculate_ec2_cost("t3.micro", hours),
            "ec2_gpu": self.calculate_ec2_cost("g4dn.xlarge", hours),
            "ebs_test": self.calculate_ebs_cost(8, hours / 730),
            "ebs_gpu": self.calculate_ebs_cost(100, hours / 730),
            "s3": self.calculate_s3_cost(5, hours / 730),
            "data_transfer": self.calculate_data_transfer_cost(10),
        }
        costs["total"] = sum(costs.values())
        return costs
    
    def scenario_production(self) -> Dict[str, float]:
        """Full production deployment (24/7 for 1 month)."""
        costs = {
            "ec2_api": self.calculate_ec2_cost("t3.medium", 730),
            "ec2_gpu": self.calculate_ec2_cost("g4dn.xlarge", 730),
            "ebs_api": self.calculate_ebs_cost(30, 1),
            "ebs_gpu": self.calculate_ebs_cost(100, 1),
            "s3": self.calculate_s3_cost(100, 1),
            "rds": PRICING["rds"]["db.t3.small"] * 730,
            "data_transfer": self.calculate_data_transfer_cost(1000),
        }
        costs["total"] = sum(costs.values())
        return costs
    
    def scenario_optimized(self) -> Dict[str, float]:
        """Optimized deployment (market hours only)."""
        hours = 12 * 22  # 264 hours/month
        costs = {
            "ec2_api": self.calculate_ec2_cost("t3.medium", 730),
            "ec2_gpu": self.calculate_ec2_cost("g4dn.xlarge", hours),
            "ebs_api": self.calculate_ebs_cost(30, 1),
            "ebs_gpu": self.calculate_ebs_cost(100, 1),
            "s3": self.calculate_s3_cost(100, 1),
            "data_transfer": self.calculate_data_transfer_cost(500),
        }
        costs["total"] = sum(costs.values())
        return costs


def print_scenario(name: str, costs: Dict[str, float], hours: float = None):
    """Pretty print scenario costs."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    if hours:
        print(f"\nDuration: {hours} hours ({hours/24:.1f} days)")
    
    print(f"\nCost Breakdown:")
    print(f"{'-'*60}")
    
    total = costs.pop("total")
    
    for service, cost in sorted(costs.items()):
        service_name = service.replace("_", " ").title()
        print(f"  {service_name:<30} ${cost:>8.2f}")
    
    print(f"{'-'*60}")
    print(f"  {'Total':<30} ${total:>8.2f}")
    
    if hours:
        hourly = total / hours
        daily = hourly * 24
        print(f"\n  Hourly rate: ${hourly:.4f}/hour")
        print(f"  Daily rate:  ${daily:.2f}/day")
    
    print()


def main():
    """Main cost calculation and display."""
    print("\n" + "="*60)
    print("  Quant AI - AWS Cost Calculator")
    print("="*60)
    print(f"\nCalculation Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Region: us-east-1")
    print(f"Using Free Tier: Yes (first 12 months)")
    
    calc = CostCalculator(use_free_tier=True)
    
    print_scenario(
        "Scenario 1: Basic Test (1 Hour)",
        calc.scenario_basic_test(1),
        hours=1
    )
    
    print_scenario(
        "Scenario 2: Basic Test (24 Hours)",
        calc.scenario_basic_test(24),
        hours=24
    )
    
    print_scenario(
        "Scenario 3: With GPU Model Server (1 Hour)",
        calc.scenario_with_gpu(1),
        hours=1
    )
    
    print_scenario(
        "Scenario 4: With GPU Model Server (24 Hours)",
        calc.scenario_with_gpu(24),
        hours=24
    )
    
    print_scenario(
        "Scenario 5: Production Deployment (1 Month, 24/7)",
        calc.scenario_production(),
    )
    
    print_scenario(
        "Scenario 6: Optimized Deployment (1 Month, Market Hours)",
        calc.scenario_optimized(),
    )
    
    print("\n" + "="*60)
    print("  Cost Comparison Summary")
    print("="*60)
    print(f"\n  1 hour basic test:              ${calc.scenario_basic_test(1)['total']:.4f}")
    print(f"  1 hour with GPU:                ${calc.scenario_with_gpu(1)['total']:.2f}")
    print(f"  24 hour basic test:             ${calc.scenario_basic_test(24)['total']:.2f}")
    print(f"  24 hour with GPU:               ${calc.scenario_with_gpu(24)['total']:.2f}")
    print(f"  1 month production (24/7):      ${calc.scenario_production()['total']:.2f}")
    print(f"  1 month optimized (market hrs): ${calc.scenario_optimized()['total']:.2f}")
    
    print("\n" + "="*60)
    print("  Recommendations")
    print("="*60)
    print("""
  For Testing (1-2 hours):
    ✅ Use basic test setup (t3.micro only)
    💰 Cost: ~$0.01 - $0.02 (essentially free with free tier)
  
  For Development (daily, few hours):
    ✅ Use GPU only when needed
    ✅ Stop instances when not in use
    💰 Cost: ~$1-2 per hour of GPU use
  
  For Production (24/7):
    ⚠️  Consider market-hours-only operation
    ⚠️  Use spot instances (70% discount)
    💰 Cost: ~$140/month (optimized) vs $450/month (always-on)
  
  💡 Pro Tips:
    • Set up billing alerts at $10, $50, $100
    • Use CloudWatch to auto-stop instances after idle time
    • Store models in S3, not EBS (cheaper)
    • Use Reserved Instances for 40% discount (1-year commitment)
    """)
    
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
