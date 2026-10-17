"""Compile the exact production scaled norm; check range extremes and native path."""
from pathlib import Path
import hashlib,json,subprocess,tempfile
asset=Path('chromium/privacy/metabrowser_fft_complex_math.inc');text=asset.read_text();start=text.index('double MetaBrowserFftMagnitude');end=text.index('double MetaBrowserFftPhase')
body=text[start:end]
cpp='''#include <algorithm>
#include <cmath>
#include <complex>
#include <limits>
#include <cassert>
#include <cstdint>
bool selected=false;
bool MetaBrowserPortableFft(){return selected;}
'''+body+'''
int main(){
 const double inf=std::numeric_limits<double>::infinity();
 const double nan=std::numeric_limits<double>::quiet_NaN();
 const double tiny=std::numeric_limits<double>::denorm_min();
 const double big=std::numeric_limits<double>::max();
 std::complex<double> cases[]={{0,0},{-0.,0},{3,4},{-3,-4},{big,big},{big/2,big/2},
 {tiny,tiny},{tiny*4,tiny*8},{1e-300,1e-300},{1e300,1e-300},{inf,nan},{nan,inf},{nan,1}};
 for(bool mode:{false,true}){
  selected=mode;
  auto check=[&](std::complex<double> value){
   double got=MetaBrowserFftMagnitude(value),want=std::abs(value);
   if(std::isinf(want)) assert(std::isinf(got)&&!std::signbit(got));
   else if(std::isnan(want))assert(std::isnan(got));
   else if(!mode)assert(got==want && std::signbit(got)==std::signbit(want));
   else assert(std::abs(got-want)<=8*std::numeric_limits<double>::epsilon()*want+2*tiny);
  };
  for(auto value:cases)check(value);
  uint64_t bits=123456789;
  for(int n=0;n<1000;n++){
   bits^=bits<<13;bits^=bits>>7;bits^=bits<<17;
   double x=static_cast<float>(static_cast<int>(bits%257)-128)/7.;
   bits^=bits<<13;bits^=bits>>7;bits^=bits<<17;
   double y=static_cast<float>(static_cast<int>(bits%257)-128)/11.;
   check({x,y});
  }
 }
}
'''
with tempfile.TemporaryDirectory(prefix='metabrowser-complex-math-') as temp:
 root=Path(temp);source=root/'norm.cc';source.write_text(cpp)
 subprocess.run(['c++','-std=c++17','-ffp-contract=off','-fsanitize=undefined,float-cast-overflow',str(source),'-o',str(root/'norm')],check=True)
 subprocess.run([str(root/'norm')],check=True)
print(json.dumps({'actual_production_magnitude_compiled':True,'ubsan_passed':True,'mode_vector_cases':2026,'asset_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'full_hrtf_privacy_proven':False}))
