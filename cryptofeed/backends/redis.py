'''
Copyright (C) 2017-2019  Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.
'''
from decimal import Decimal
import time
import json

import aioredis

from cryptofeed.standards import timestamp_normalize
from cryptofeed.defines import BID, ASK
from cryptofeed.backends._util import book_convert, book_flatten


class RedisCallback:
    def __init__(self, host='127.0.0.1', port=6379, key=None, **kwargs):
        """
        setting key lets you override the prefix on the
        key used in redis. The defaults are related to the data
        being stored, i.e. trade, funding, etc
        """
        self.host = host
        self.port = port
        self.redis = None
        self.key = key


class TradeRedis(RedisCallback):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.key is None:
            self.key = 'trades'

    async def __call__(self, *, feed: str, pair: str, side: str, amount: Decimal, price: Decimal, order_id=None, timestamp=None):
        if self.redis is None:
            self.redis = await aioredis.create_redis_pool('redis://{}:{}'.format(self.host, self.port))
        ts = None
        if timestamp is None:
            timestamp = time.time()
            ts = timestamp
        else:
            ts = timestamp_normalize(feed, timestamp)

        data = json.dumps({'feed': feed, 'pair': pair, 'id': order_id, 'timestamp': timestamp,
                           'side': side, 'amount': str(amount), 'price': str(price)})

        await self.redis.zadd("{}-{}-{}".format(self.key, feed, pair), ts, data, exist=self.redis.ZSET_IF_NOT_EXIST)


class TradeStream(TradeRedis):
    async def __call__(self, *, feed: str, pair: str, side: str, amount: Decimal, price: Decimal, order_id=None, timestamp=None):
        if self.redis is None:
            self.redis = await aioredis.create_redis_pool('redis://{}:{}'.format(self.host, self.port))

        data = {'feed': feed, 'pair': pair, 'id': order_id, 'timestamp': timestamp,
                'side': side, 'amount': str(amount), 'price': str(price)}

        await self.redis.xadd(f"{self.key}-{feed}-{pair}", data)


class FundingRedis(RedisCallback):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.key is None:
            self.key = 'funding'

    async def __call__(self, *, feed, pair, **kwargs):
        if self.redis is None:
            self.redis = await aioredis.create_redis_pool('redis://{}:{}'.format(self.host, self.port))

        ts = None
        timestamp = kwargs.get('timestamp', None)

        if timestamp is None:
            timestamp = time.time()
            ts = timestamp
        else:
            ts = timestamp_normalize(feed, timestamp)

        for key in kwargs:
            if isinstance(kwargs[key], Decimal):
                kwargs[key] = str(kwargs[key])

        data = json.dumps(kwargs)

        await self.redis.zadd("{}-{}-{}".format(self.key, feed, pair), ts, data, exist=self.redis.ZSET_IF_NOT_EXIST)


class FundingStream(FundingRedis):
    async def __call__(self, *, feed, pair, **kwargs):
        if self.redis is None:
            self.redis = await aioredis.create_redis_pool('redis://{}:{}'.format(self.host, self.port))

        for key in kwargs:
            if isinstance(kwargs[key], Decimal):
                kwargs[key] = str(kwargs[key])

        await self.redis.xadd(f"{self.key}-{feed}-{pair}", kwargs)


class BookRedis(RedisCallback):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.key is None:
            self.key = 'book'
        self.depth = kwargs.get('depth', None)
        self.previous = {BID: {}, ASK: {}}

    async def __call__(self, *, feed, pair, book, timestamp):
        ts = time.time()

        if self.redis is None:
            self.redis = await aioredis.create_redis_pool('redis://{}:{}'.format(self.host, self.port))

        data = {'timestamp': timestamp_normalize(feed, timestamp), BID: {}, ASK: {}}
        book_convert(book, data, self.depth)

        if self.depth:
            if data[BID] == self.previous[BID] and data[ASK] == self.previous[ASK]:
                return
            self.previous[ASK] = data[ASK]
            self.previous[BID] = data[BID]

        data = json.dumps(data)
        await self.redis.zadd("{}-{}-{}".format(self.key, feed, pair), ts, data, exist=self.redis.ZSET_IF_NOT_EXIST)


class BookStream(BookRedis):
    async def __call__(self, *, feed, pair, book, timestamp):
        if self.redis is None:
            self.redis = await aioredis.create_redis_pool('redis://{}:{}'.format(self.host, self.port))

        data = {'timestamp': timestamp_normalize(feed, timestamp), BID: {}, ASK: {}}
        book_convert(book, data, self.depth)

        if self.depth:
            if data[BID] == self.previous[BID] and data[ASK] == self.previous[ASK]:
                return
            self.previous[ASK] = data[ASK]
            self.previous[BID] = data[BID]

        flat = book_flatten(data, data['timestamp'])
        for update in flat:
            await self.redis.xadd(f"{self.key}-{feed}-{pair}", update)
