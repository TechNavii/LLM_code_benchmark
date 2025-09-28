use std::hash::Hash;

pub struct LruCache<K, V> {
    _marker: std::marker::PhantomData<(K, V)>,
}

impl<K: Eq + Hash + Clone, V: Clone> LruCache<K, V> {
    pub fn new(_capacity: usize) -> Self {
        unimplemented!("new not implemented")
    }

    pub fn len(&self) -> usize {
        unimplemented!("len not implemented")
    }

    pub fn get(&mut self, _key: &K) -> Option<V> {
        unimplemented!("get not implemented")
    }

    pub fn put(&mut self, _key: K, _value: V) {
        unimplemented!("put not implemented")
    }
}
