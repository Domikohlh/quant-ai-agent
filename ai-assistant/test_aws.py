"""
Test AWS IAM permissions for Quant AI project.
"""
import boto3
from botocore.exceptions import ClientError

def test_permissions():
    """Test if IAM user has necessary permissions."""
    
    tests = []
    
    # Test EC2 permissions
    try:
        ec2 = boto3.client('ec2', region_name='us-east-1')
        ec2.describe_instances()
        tests.append(("✅ EC2 describe_instances", True))
    except ClientError as e:
        tests.append(("❌ EC2 describe_instances", False))
        print(f"   Error: {e}")
    
    # Test S3 permissions
    try:
        s3 = boto3.client('s3')
        s3.list_buckets()
        tests.append(("✅ S3 list_buckets", True))
    except ClientError as e:
        tests.append(("❌ S3 list_buckets", False))
        print(f"   Error: {e}")
    
    # Test CloudWatch permissions
    try:
        cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')
        cloudwatch.list_metrics()
        tests.append(("✅ CloudWatch list_metrics", True))
    except ClientError as e:
        tests.append(("❌ CloudWatch list_metrics", False))
        print(f"   Error: {e}")
    
    # Test IAM permissions
    try:
        iam = boto3.client('iam')
        iam.get_user()
        tests.append(("✅ IAM get_user", True))
    except ClientError as e:
        tests.append(("❌ IAM get_user", False))
        print(f"   Error: {e}")
    
    # Print summary
    print("\n" + "="*50)
    print("AWS Permissions Test Summary")
    print("="*50)
    for test_name, result in tests:
        print(test_name)
    
    passed = sum(1 for _, result in tests if result)
    total = len(tests)
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("\n✅ All permissions configured correctly!")
    else:
        print("\n⚠️  Some permissions are missing. Review IAM policy.")

if __name__ == "__main__":
    test_permissions()
