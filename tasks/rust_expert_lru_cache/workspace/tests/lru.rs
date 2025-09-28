use rust_expert_lru_cache::LruCache;

#[test]
fn panics_on_zero_capacity() {
    let result = std::panic::catch_unwind(|| LruCache::<u32, u32>::new(0));
    assert!(result.is_err());
}

#[test]
fn eviction_respects_lru_order() {
    let mut cache = LruCache::new(3);
    cache.put("a", 1);
    cache.put("b", 2);
    cache.put("c", 3);
    assert_eq!(cache.len(), 3);

    // Access a to keep it fresh.
    assert_eq!(cache.get(&"a"), Some(1));

    // Insert new key, oldest should be b.
    cache.put("d", 4);
    assert_eq!(cache.len(), 3);
    assert_eq!(cache.get(&"b"), None);
    assert_eq!(cache.get(&"c"), Some(3));
    assert_eq!(cache.get(&"d"), Some(4));
}

#[test]
fn updates_do_not_increase_length() {
    let mut cache = LruCache::new(2);
    cache.put("x", 10);
    cache.put("x", 20);
    assert_eq!(cache.len(), 1);
    assert_eq!(cache.get(&"x"), Some(20));
}

#[test]
fn heavy_rotation_keeps_recent_keys() {
    let mut cache = LruCache::new(4);
    for i in 0..12 {
        let key = format!("k{}", i % 6);
        cache.put(key.clone(), i);
        let _ = cache.get(&key);
    }
    for i in 2..6 {
        let key = format!("k{}", i);
        assert!(cache.get(&key).is_some(), "expected {} to remain", key);
    }
}
