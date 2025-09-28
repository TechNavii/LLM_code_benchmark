use rust_expert_time_bucketer::{bucketize, Bucket};

#[test]
fn basic_bucketing_with_gap() {
    let points = vec![(5, 10.0), (8, 14.0), (17, 18.0)];
    let buckets = bucketize(&points, 5);
    assert_eq!(buckets.len(), 3);
    assert_eq!(
        buckets[0],
        Bucket {
            start: 5,
            end: 10,
            count: 2,
            average: 12.0,
            min: 10.0,
            max: 14.0,
        }
    );
    assert_eq!(
        buckets[1],
        Bucket {
            start: 10,
            end: 15,
            count: 0,
            average: 12.0,
            min: 10.0,
            max: 14.0,
        }
    );
    assert_eq!(
        buckets[2],
        Bucket {
            start: 15,
            end: 20,
            count: 1,
            average: 18.0,
            min: 18.0,
            max: 18.0,
        }
    );
}

#[test]
fn handles_negative_timestamps() {
    let points = vec![(-7, -1.0), (-2, 3.0)];
    let buckets = bucketize(&points, 4);
    assert_eq!(buckets.len(), 3);
    assert_eq!(buckets[0].start, -8);
    assert_eq!(buckets[0].average, -1.0);
    assert_eq!(buckets[1].count, 0);
    assert_eq!(buckets[1].average, -1.0);
    assert_eq!(buckets[2].average, 3.0);
}

#[test]
fn propagates_statistics_over_long_range() {
    let mut points = Vec::new();
    for i in 0..50 {
        points.push((i * 3, (i % 7) as f64));
    }
    let buckets = bucketize(&points, 9);
    assert!(buckets.len() >= 17);
    // ensure last bucket contains last point
    let last = buckets.last().unwrap();
    assert!(last.start <= 147 && last.end >= 147 + 1);
    assert_eq!(last.count > 0, true);
}

#[test]
#[should_panic(expected = "width")]
fn rejects_non_positive_width() {
    let _ = bucketize(&[(0, 0.0)], 0);
}
