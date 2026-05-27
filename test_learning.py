"""
test_learning.py — Test script for learning memory system
"""
import learning_memory as lm
import db

# Initialize systems
print("Initializing database...")
db.init_db()

print("Initializing learning memory system...")
lm.initialize_learning_system()

print("\n✅ Learning system initialized successfully!")

# Test platform performance
print("\n--- Platform Performance ---")
platforms = lm.get_all_platform_performance()
for p in platforms:
    print(f"{p['platform']:12s} | Attempts: {p['total_attempts']} | Success: {p['successful']} | Earnings: ${p['total_earnings']:.2f}")

# Test scoring weights
print("\n--- Scoring Weights ---")
weights = lm.get_all_scoring_weights()
for name, value in weights.items():
    print(f"{name:25s} = {value:.2f}")

# Test recommendations
print("\n--- Recommendations ---")
recommendations = lm.get_recommendations()
for i, rec in enumerate(recommendations, 1):
    print(f"{i}. {rec}")

# Test learning summary
print("\n--- Learning Summary ---")
summary = lm.get_learning_summary()
print(f"High confidence patterns: {summary['high_confidence_patterns']}")
print(f"Learning events (7d): {summary['learning_events_7d']}")
print(f"Complexity accuracy: {summary['complexity_accuracy']}")

print("\n✅ All tests passed!")
