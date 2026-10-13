import pandas as pd
import streamlit as st
import altair as alt
# 1分刻み(約4300点×4系列)が既定の行数上限(5000)を超えるため解除
alt.data_transformers.disable_max_rows()
from datetime import timedelta
from datetime import time

## 列挙型
class Company( int ):
	ORIX	= 0
	MITSUI	= 1
	TIMES	= 2
	TOYOTA	= 3
	MAX		= 4

# データ定義
## 上限
LIMIT = 4320

## 月会費
MONTHLY = {
	Company.ORIX:	0,
	Company.MITSUI:	880,
	Company.TIMES:	880,
	Company.TOYOTA:	0
}

## 基本料金(何分単位)
BASE_TIME = {
	Company.ORIX:	15,
	Company.MITSUI:	10,
	Company.TIMES:	15,
	Company.TOYOTA:	15
}

## 基本料金(何円)
BASE_PRICE = {
	Company.ORIX:	240,
	Company.MITSUI:	150,
	Company.TIMES:	220,
	Company.TOYOTA:	220
}

## 6時間まで
TO_6_HOUR = {
	Company.ORIX:	4190,
	Company.MITSUI:	4280,
	Company.TIMES:	4290,
	Company.TOYOTA:	5610
}

## 12時間まで
TO_12_HOUR = {
	Company.ORIX:	5390,
	Company.MITSUI:	5700,
	Company.TIMES:	5500,
	Company.TOYOTA:	5940
}

## 24時間まで
TO_24_HOUR = {
	Company.ORIX:	7890,
	Company.MITSUI:	7300,
	Company.TIMES:	6600,
	Company.TOYOTA:	7810
}

## 48時間まで
TO_48_HOUR = {
	Company.TIMES:	9900
}

## 72時間まで
TO_72_HOUR = {
	Company.TIMES:	14300
}

## 以降1時間ごとに
ADDITIONAL_1_HOUR = {
	Company.TOYOTA:	1210
}

## 以降24時間ごとに
ADDITIONAL_24_HOUR = {
	Company.ORIX:	4190,
	Company.TIMES:	5500,
	Company.TOYOTA:	6600
}

## 最大時間料金
MAX_TIME_PRICE = {
	Company.ORIX:	True
}


def auto_getters_setters( *members ):
	"""複数のメンバーに対してゲッター・セッターを自動生成"""
	def decorator( cls ):
		for member in members:
			attr_name = f'_{cls.__name__}__{member}'

			# ゲッター
			def make_getter( attr ):
				return lambda self: getattr( self, attr )
			setattr( cls, f'get_{member}', make_getter( attr_name ) )

			# セッター
			def make_setter( attr ):
				return lambda self, v: setattr( self, attr, v )
			setattr( cls, f'set_{member}', make_setter( attr_name ) )
		return cls
	return decorator

# カーシェアクラス
## ゲッター・セッター自動生成
@auto_getters_setters( 'monthly', 'base', 'time_price', 'additional', 'max_time_price' )
class CarShare:
	## コンストラクタ
	def __init__( self ):
		self.__monthly			= 0
		self.__base				= {}
		self.__time_price		= {}
		self.__additional		= {}
		self.__max_time_price	= False

	## 基本料金更新
	def update_base( self, time, price ):
		self.__base[ timedelta( minutes=time ) ] = price

	## 時間料金更新
	def update_time_price( self, time, price ):
		self.__time_price[ timedelta( hours=time ) ] = price

	## 超過料金更新
	def update_additional( self, time, price ):
		self.__additional[ timedelta( hours=time ) ] = price

	## 追加料金の計算(超えた時間に収まる追加料金を、選択した分だけ加算)
	def _calc_additional_price( self, overflow_time ):
		additional_price = 0
		while overflow_time > timedelta( 0 ):
			time, price = self._pick_additional( overflow_time )
			additional_price += price
			overflow_time -= time
		return additional_price

	## 追加料金の選択(超えた時間に収まる追加料金のうち最も高いものを返す。収まるものが無ければ最も短い追加料金)
	def _pick_additional( self, overflow_time ):
		chosen = None
		for time, price in self.get_additional().items():
			if time <= overflow_time and ( chosen is None or price > chosen[ 1 ] ):
				chosen = ( time, price )
		if chosen is None:
			chosen = min( self.get_additional().items() )
		return chosen

	## 最大時間料金の計算
	def _calc_max_price( self, total_time ):
		longest_time, longest_price = max( self.get_time_price().items() )
		# 最長区分以内は、利用時間を含む最小の区分の料金を使う(最長区分を超える場合は該当する区分が無いので、そのまま下へ進む)
		for time, price in sorted( self.get_time_price().items() ):
			if time >= total_time:
				return price
		# 最長区分の料金を基準に、超えた分は追加料金を加算
		if not self.get_additional():
			return longest_price
		return longest_price + self._calc_additional_price( total_time - longest_time )

	## 区分の検索(直前の区分と、利用時間を含む区分の料金を返す)
	def _find_tiers( self, remaining_time ):
		_, longest_price = max( self.get_time_price().items() )
		lower_time, lower_price = None, None
		tier_price = longest_price
		for time, price in sorted( self.get_time_price().items() ):
			if time < remaining_time:
				lower_time, lower_price = time, price
			else:
				tier_price = price
				break
		return lower_time, lower_price, tier_price

	## 基本料金(利用時間を基本時間ごとに切り上げて、基本料金を積み上げた額)
	def _base_fee( self, duration ):
		if not self.get_base():
			return 0
		base_time, base_price = next( iter( self.get_base().items() ) )
		return -( -duration // base_time ) * base_price

	## 最長区分を超えた分の料金と、最大時間料金との比較に使う時間を返す
	def _over_longest( self, remaining_time, longest_time, longest_price ):
		if self.get_additional():
			return longest_price + self._calc_additional_price( remaining_time - longest_time ), remaining_time
		# 追加料金がない場合は、基本料金を基本時間ごとに積み上げる(切り上げた時間を返す)
		base_time, base_price = next( iter( self.get_base().items() ) )
		blocks = -( -( remaining_time - longest_time ) // base_time )
		return longest_price + blocks * base_price, longest_time + blocks * base_time

	## 料金計算
	def calc_price( self, minute ):
		# 料金計算用の変数を初期化
		total_price = self.get_monthly()
		remaining_time = timedelta( minutes=minute )
		longest_time, longest_price = max( self.get_time_price().items() )
		# 最大時間料金との比較に使う時間
		billed_time = remaining_time

		# 最長区分(24時間)を超えた分は、最長区分の料金を基準にする
		if remaining_time > longest_time:
			over_price, billed_time = self._over_longest( remaining_time, longest_time, longest_price )
			total_price += over_price

		# 最小の時間区分未満は、基本料金を基本時間ごとに加算(切り上げ)
		elif remaining_time < min( self.get_time_price() ):
			total_price += self._base_fee( remaining_time )
		else:
			lower_time, lower_price, tier_price = self._find_tiers( remaining_time )
			# 直前の区分を超えた分は基本料金を基本時間ごとに加算し、次の区分の料金より安ければそちらを採用
			if lower_time is not None and self.get_base():
				tier_price = min( tier_price, lower_price + self._base_fee( remaining_time - lower_time ) )
			total_price += tier_price

		# 最大時間料金と比較して、安い方を採用
		if self.get_max_time_price():
			total_price = min( total_price, self._calc_max_price( billed_time ) )

		return total_price

def main():
	# インスタンスを生成し、リストに代入
	lService = [ CarShare() for i in range( Company.MAX ) ]
	for i in range( Company.MAX ):
		# 各メンバー変数を更新
		## データ定義に値がある場合のみ更新
		if i in MONTHLY:
			lService[i].set_monthly( MONTHLY[i] )
		if i in BASE_TIME:
			lService[i].update_base( BASE_TIME[i], BASE_PRICE[i] )
		for hour, table in [ ( 6, TO_6_HOUR ), ( 12, TO_12_HOUR ), ( 24, TO_24_HOUR ), ( 48, TO_48_HOUR ), ( 72, TO_72_HOUR ) ]:
			if i in table:
				lService[i].update_time_price( hour, table[i] )
		for hour, table in [ ( 1, ADDITIONAL_1_HOUR ), ( 24, ADDITIONAL_24_HOUR ) ]:
			if i in table:
				lService[i].update_additional( hour, table[i] )
		lService[i].set_max_time_price( MAX_TIME_PRICE.get( i, False ) )

	# データフレーム作成
	## X軸
	lHour		= [ i for i in range( LIMIT + 1 ) ]
	## Y軸
	lTotalPrice	= {
		name: []
		for name, value in vars(Company).items()
		if isinstance(value, int) and not name.startswith('_') and name != 'MAX'
	}
	for i in lHour:
		# 料金計算
		for j in range( Company.MAX ):
			lTotalPrice[ list( lTotalPrice.keys() )[ j ] ].append( lService[ j ].calc_price( i ) )

	# 軸タイトルを付けるため Altair で描画(st.line_chart では軸タイトルを指定できない)
	df = pd.DataFrame( lTotalPrice, index=[ i / 60 for i in lHour ] )
	df.index.name = '時間'
	df = df.reset_index().melt( '時間', var_name='会社', value_name='料金' )
	chart = alt.Chart( df ).mark_line().encode(
		x=alt.X( '時間:Q', title='時間' ),
		y=alt.Y( '料金:Q', title='円', axis=alt.Axis( titleAngle=0, titleAlign='left', titleY=-12 ) ),
		color='会社:N'
	)
	st.altair_chart( chart )


if __name__ == "__main__":
	main()
